// ctr_drbg -- NIST SP 800-90A CTR_DRBG, AES-128, block-cipher derivation
// function, no prediction resistance (decision record 0002).
//
// Scope: the DRBG control and state only. The AES engine is NOT inside this
// module: it is a master port (aes_*) onto a shared aes_core, which this
// module holds exclusively from the cycle it accepts a command until `done`
// (spec/decision-records/0002). The seed buffer is NOT inside this module
// either: the seed is read from the `seed` input, which the owner (trng_if)
// must hold stable while `busy` is high. Makes no entropy, security or
// side-channel claim; a passing known-answer test is a correctness claim only
// (decision record 0008).
//
// Parameters (elaboration time):
//   INST_WORDS   32-bit words of entropy_input || nonce for instantiate.
//                Shipped value 16 (256-bit entropy + 256-bit nonce, 0002).
//   RESEED_WORDS 32-bit words of entropy_input for reseed. Shipped value 8.
//   RESEED_INTERVAL generate requests allowed between (re)seeds. Shipped
//                value 65536 (2^16, 0002). A bench uses a small value.
// The df encodes the input length in S, so any other word count is a
// different function; the CAVP replay elaborates 6/4 words (24-byte
// entropy||nonce, 16-byte reseed) to match the published vectors, and the
// shipped width is checked against verification/model/ctr_drbg.py.
//
// Seed byte order (0002): word i is seed[32*i +: 32]; the df input stream is
// word 0 first, each word most-significant byte first.
//
// Commands: one-cycle pulses cmd_inst / cmd_reseed / cmd_gen, accepted only
// while busy is low (cmd_inst wins over cmd_reseed over cmd_gen).
//   cmd_inst   Instantiate from seed[INST_WORDS words]. Clears `seeded`
//              until it completes.
//   cmd_reseed Reseed from seed[RESEED_WORDS words]; error if not seeded.
//   cmd_gen    Generate gen_bits (1..1024) bits, streamed as ceil(bits/128)
//              blocks on blk_data/blk_valid/blk_last, one block per AES call,
//              no back-pressure (the consumer buffers). SP 800-90A Update
//              runs after every request. No additional input.
// `done` pulses for one cycle when a command finishes; `err` (valid with done
// and until the next command) is 0 ok, 1 not instantiated, 2 reseed required,
// 3 request size out of range. A refused command produces no data.
//
// zeroize: synchronous, highest priority; clears every key-bearing and
// working register (key_q, v_q, chain_q, tk_q, tx_q, t0_q, prov_q,
// blk_data_q), the output strobes, the state machine and the `seeded` flag,
// in one edge. There is no reset: the owner asserts zeroize after power-up.

module ctr_drbg #(
    parameter INST_WORDS      = 16,
    parameter RESEED_WORDS    = 8,
    parameter RESEED_INTERVAL = 65536
) (
`ifdef FORMAL
    output wire         fv_zero,
`endif
    input  wire         clk,
    input  wire         zeroize,

    input  wire         cmd_inst,
    input  wire         cmd_reseed,
    input  wire         cmd_gen,
    input  wire [10:0]  gen_bits,
    input  wire [32*((INST_WORDS > RESEED_WORDS) ? INST_WORDS : RESEED_WORDS)-1:0] seed,

    output wire         busy,
    output wire         done,
    output wire [1:0]   err,
    output wire         seeded,
    output wire         reseed_required,

    output wire         blk_valid,
    output wire         blk_last,
    output wire [127:0] blk_data,

    output wire         aes_start,
    output wire [127:0] aes_key,
    output wire [127:0] aes_block,
    input  wire         aes_busy,
    input  wire         aes_done,
    input  wire [127:0] aes_out
);

    localparam SEEDW   = 32 * ((INST_WORDS > RESEED_WORDS) ? INST_WORDS : RESEED_WORDS);
    localparam CTR_W   = $clog2(RESEED_INTERVAL + 2);
    localparam NS_INST = (9 + 4 * INST_WORDS + 15) / 16;     // 16-byte blocks of S
    localparam NS_RSD  = (9 + 4 * RESEED_WORDS + 15) / 16;
`ifdef DRBG_NEG_DF
    localparam [127:0] K0 = 128'h000102030405060708090a0b0c0d0e0e;   // negative control: one bit of the df key
`else
    localparam [127:0] K0 = 128'h000102030405060708090a0b0c0d0e0f;
`endif

    localparam [1:0] OP_INST = 2'd0, OP_RESEED = 2'd1, OP_GEN = 2'd2;
    localparam [3:0] S_IDLE = 4'd0, S_DF_ISSUE = 4'd1, S_DF_WAIT = 4'd2,
                     S_OUT_ISSUE = 4'd3, S_OUT_WAIT = 4'd4,
                     S_UPD_ISSUE = 4'd5, S_UPD_WAIT = 4'd6,
                     S_GEN_ISSUE = 4'd7, S_GEN_WAIT = 4'd8;

    reg [3:0]   state_q;
    reg [1:0]   op_q;
    reg         seeded_q;
    reg [CTR_W-1:0] ctr_q;          // SP 800-90A reseed_counter
    reg [127:0] key_q;
    reg [127:0] v_q;
    reg [127:0] chain_q;            // BCC chaining value
    reg [127:0] tk_q;               // df: first BCC output (the df key)
    reg [127:0] tx_q;               // df: second BCC output (the df X)
    reg [127:0] t0_q;               // Update: first keystream block
    reg [255:0] prov_q;             // provided_data for Update
    reg         iter_q;             // df iteration index (0 or 1)
    reg [3:0]   blk_q;              // df: block index within the iteration
    reg         ocnt_q;             // df output stage / Update: second call
    reg [3:0]   gcnt_q;             // generate: blocks produced
    reg [3:0]   gtot_q;             // generate: blocks requested
    reg [1:0]   err_q;
    reg         done_q;
    reg         bv_q, bl_q;
    reg [127:0] bd_q;

    assign busy            = (state_q != S_IDLE);
    assign done            = done_q;
    assign err             = err_q;
    assign seeded          = seeded_q;
    assign reseed_required = seeded_q && (ctr_q > RESEED_INTERVAL);
    assign blk_valid       = bv_q;
    assign blk_last        = bl_q;
    assign blk_data        = bd_q;

    // -- derivation-function input ------------------------------------------
    wire [31:0] l_bytes  = (op_q == OP_RESEED) ? 4 * RESEED_WORDS : 4 * INST_WORDS;
    wire [3:0]  last_blk = (op_q == OP_RESEED) ? NS_RSD : NS_INST;   // IV is block 0

    // Block bi (>= 1) of S = L(4) || N(4) || data || 0x80 || zero pad.
    function [127:0] sblock;
        input [3:0]       bi;
        input [31:0]      lb;
        input [SEEDW-1:0] sd;
        integer b, pos, d;
        reg [7:0] y;
        begin
            for (b = 0; b < 16; b = b + 1) begin
                pos = 16 * (bi - 1) + b;
                if (pos < 4)            y = lb >> (8 * (3 - pos));
                else if (pos < 8)       y = (pos == 7) ? 8'h20 : 8'h00;   // N = 32 bytes = seedlen
                else if (pos < 8 + lb)  begin d = pos - 8; y = sd[32 * (d / 4) + 8 * (3 - d % 4) +: 8]; end
                else if (pos == 8 + lb) y = 8'h80;
                else                    y = 8'h00;
                sblock[127 - 8 * b -: 8] = y;
            end
        end
    endfunction

    wire [127:0] iv_blk   = {31'd0, iter_q, 96'd0};
    wire [127:0] df_data  = (blk_q == 4'd0) ? iv_blk : sblock(blk_q, l_bytes, seed);
    wire [127:0] v_inc    = v_q + 128'd1;

    // -- AES master port ----------------------------------------------------
    wire issuing = (state_q == S_DF_ISSUE) || (state_q == S_OUT_ISSUE) ||
                   (state_q == S_UPD_ISSUE) || (state_q == S_GEN_ISSUE);
    assign aes_start = issuing && !aes_busy;
    assign aes_key   = (state_q == S_DF_ISSUE || state_q == S_DF_WAIT)   ? K0 :
                       (state_q == S_OUT_ISSUE || state_q == S_OUT_WAIT) ? tk_q : key_q;
    assign aes_block = (state_q == S_DF_ISSUE || state_q == S_DF_WAIT)   ? (chain_q ^ df_data) :
                       (state_q == S_OUT_ISSUE || state_q == S_OUT_WAIT) ? (ocnt_q ? prov_q[255:128] : tx_q) :
                                                                          v_inc;

    // Update completes: new Key/V.
`ifdef DRBG_NEG_UPD
    wire [127:0] upd_v = (aes_out ^ prov_q[127:0]) ^ 128'd1;   // negative control: one bit of V
`else
    wire [127:0] upd_v = aes_out ^ prov_q[127:0];
`endif

    wire [4:0] nblocks_req = {1'b0, gen_bits[10:7]} + {4'd0, |gen_bits[6:0]};
    wire       size_ok     = (gen_bits != 11'd0) && (gen_bits <= 11'd1024);

    always @(posedge clk) begin
        done_q <= 1'b0;
        bv_q   <= 1'b0;
        bl_q   <= 1'b0;
        if (zeroize) begin
            state_q  <= S_IDLE;
            op_q     <= OP_INST;
            seeded_q <= 1'b0;
            ctr_q    <= {CTR_W{1'b0}};
            key_q    <= 128'd0;
`ifndef DRBG_NEG_ZEROIZE                                              // negative control: V survives zeroize
            v_q      <= 128'd0;
`endif
            chain_q  <= 128'd0;
            tk_q     <= 128'd0;
            tx_q     <= 128'd0;
            t0_q     <= 128'd0;
            prov_q   <= 256'd0;
            iter_q   <= 1'b0;
            blk_q    <= 4'd0;
            ocnt_q   <= 1'b0;
            gcnt_q   <= 4'd0;
            gtot_q   <= 4'd0;
            err_q    <= 2'd0;
            done_q   <= 1'b0;
            bd_q     <= 128'd0;
        end else begin
            case (state_q)
                S_IDLE: begin
                    if (cmd_inst) begin
                        op_q     <= OP_INST;
                        seeded_q <= 1'b0;
                        key_q    <= 128'd0;
                        v_q      <= 128'd0;
                        chain_q  <= 128'd0;
                        iter_q   <= 1'b0;
                        blk_q    <= 4'd0;
                        err_q    <= 2'd0;
                        state_q  <= S_DF_ISSUE;
                    end else if (cmd_reseed) begin
                        if (!seeded_q) begin
                            err_q  <= 2'd1;
                            done_q <= 1'b1;
                        end else begin
                            op_q    <= OP_RESEED;
                            chain_q <= 128'd0;
                            iter_q  <= 1'b0;
                            blk_q   <= 4'd0;
                            err_q   <= 2'd0;
                            state_q <= S_DF_ISSUE;
                        end
                    end else if (cmd_gen) begin
`ifdef DRBG_NEG_SEEDED
                        if (1'b0) begin                                      // negative control: generate before instantiate
`else
                        if (!seeded_q) begin
`endif
                            err_q  <= 2'd1;
                            done_q <= 1'b1;
`ifdef DRBG_NEG_INTERVAL
                        end else if (ctr_q > RESEED_INTERVAL + 1) begin    // negative control: one request too many
`else
                        end else if (ctr_q > RESEED_INTERVAL) begin
`endif
                            err_q  <= 2'd2;
                            done_q <= 1'b1;
                        end else if (!size_ok) begin
                            err_q  <= 2'd3;
                            done_q <= 1'b1;
                        end else begin
                            op_q    <= OP_GEN;
                            gtot_q  <= nblocks_req[3:0];
                            gcnt_q  <= 4'd0;
                            err_q   <= 2'd0;
                            state_q <= S_GEN_ISSUE;
                        end
                    end
                end

                // -- Block_Cipher_df: two BCC passes over IV_i || S ----------
                S_DF_ISSUE: if (!aes_busy) state_q <= S_DF_WAIT;
                S_DF_WAIT: if (aes_done) begin
                    if (blk_q == last_blk) begin
                        blk_q   <= 4'd0;
                        chain_q <= 128'd0;
                        if (!iter_q) begin
                            tk_q    <= aes_out;
                            iter_q  <= 1'b1;
                            state_q <= S_DF_ISSUE;
                        end else begin
                            tx_q    <= aes_out;
                            ocnt_q  <= 1'b0;
                            state_q <= S_OUT_ISSUE;
                        end
                    end else begin
                        chain_q <= aes_out;
                        blk_q   <= blk_q + 4'd1;
                        state_q <= S_DF_ISSUE;
                    end
                end

                // -- df output: X = E(K, X) twice -> provided_data ----------
                S_OUT_ISSUE: if (!aes_busy) state_q <= S_OUT_WAIT;
                S_OUT_WAIT: if (aes_done) begin
                    if (!ocnt_q) begin
                        prov_q[255:128] <= aes_out;
                        ocnt_q          <= 1'b1;
                        state_q         <= S_OUT_ISSUE;
                    end else begin
                        prov_q[127:0] <= aes_out;
                        ocnt_q        <= 1'b0;
                        state_q       <= S_UPD_ISSUE;
                    end
                end

                // -- Update(provided_data, Key, V) ---------------------------
                S_UPD_ISSUE: if (!aes_busy) state_q <= S_UPD_WAIT;
                S_UPD_WAIT: if (aes_done) begin
                    if (!ocnt_q) begin
                        t0_q    <= aes_out;
                        v_q     <= v_inc;
                        ocnt_q  <= 1'b1;
                        state_q <= S_UPD_ISSUE;
                    end else begin
                        key_q <= t0_q ^ prov_q[255:128];
                        v_q     <= upd_v;
                        // working registers do not persist past the command
                        t0_q    <= 128'd0;
                        tk_q    <= 128'd0;
                        tx_q    <= 128'd0;
                        prov_q  <= 256'd0;
                        ocnt_q  <= 1'b0;
                        state_q <= S_IDLE;
                        done_q  <= 1'b1;
                        err_q   <= 2'd0;
                        case (op_q)
                            OP_INST:   begin seeded_q <= 1'b1; ctr_q <= 1; end
                            OP_RESEED: ctr_q <= 1;
                            default:   ctr_q <= ctr_q + 1'b1;
                        endcase
                    end
                end

                // -- Generate: keystream blocks, then Update with zeros ------
                S_GEN_ISSUE: if (!aes_busy) state_q <= S_GEN_WAIT;
                S_GEN_WAIT: if (aes_done) begin
                    v_q  <= v_inc;
                    bd_q <= aes_out;
                    bv_q <= 1'b1;
                    gcnt_q <= gcnt_q + 4'd1;
                    if (gcnt_q + 4'd1 == gtot_q) begin
                        bl_q    <= 1'b1;
                        prov_q  <= 256'd0;
                        ocnt_q  <= 1'b0;
                        state_q <= S_UPD_ISSUE;
                    end else begin
                        state_q <= S_GEN_ISSUE;
                    end
                end

                default: state_q <= S_IDLE;
            endcase
        end
    end

`ifdef FORMAL
    assign fv_zero = (key_q == 128'd0) && (v_q == 128'd0) && (chain_q == 128'd0) &&
                     (tk_q == 128'd0) && (tx_q == 128'd0) && (t0_q == 128'd0) &&
                     (prov_q == 256'd0) && (bd_q == 128'd0) && !bv_q && !bl_q &&
                     !seeded_q && (state_q == S_IDLE);

    // The properties hold for every state reachable from a zeroize (there is no
    // reset): f_zeroed is set by the first zeroize and gates every assertion.
    reg f_zeroed = 1'b0;
    always @(posedge clk) if (zeroize) f_zeroed <= 1'b1;
    wire f_on = f_zeroed;

    // P-7: output valid implies seeded and not reseed_required.
    always @* if (f_on) assert (!bv_q || (seeded_q && !(ctr_q > RESEED_INTERVAL)));
    // P-8: the counter never exceeds interval + 1 (induction, not 2^16 steps) ...
    always @* if (f_on) assert (ctr_q <= RESEED_INTERVAL + 1);
    // ... a generate is never started while the interval is exhausted ...
    always @* if (f_on && state_q == S_GEN_ISSUE) assert (ctr_q <= RESEED_INTERVAL && seeded_q);
    // ... and the exhausted state persists until a reseed completes.
    reg f_prev_zeroize = 1'b0, f_prev_over = 1'b0, f_prev_reseed_done = 1'b0, f_prev_on = 1'b0, f_prev_inst = 1'b0;
    always @(posedge clk) begin
        f_prev_on          <= f_on;
        f_prev_zeroize     <= zeroize;
        f_prev_inst        <= (state_q == S_IDLE) && cmd_inst;
        f_prev_over        <= seeded_q && (ctr_q > RESEED_INTERVAL);
        f_prev_reseed_done <= (state_q == S_UPD_WAIT) && aes_done && ocnt_q && (op_q != OP_GEN);
        if (f_prev_on && f_prev_over && !f_prev_zeroize && !f_prev_reseed_done && !f_prev_inst)
            assert (seeded_q && (ctr_q > RESEED_INTERVAL));
    end
`endif

endmodule
