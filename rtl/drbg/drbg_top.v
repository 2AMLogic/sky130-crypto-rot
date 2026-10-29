// drbg_top -- CTR_DRBG + its AES engine + trng_if, with the small control
// sequence that ties a seed collection to a DRBG command. This is the block
// that benches and the P-9 composition check exercise; the register bus and
// the shared-engine arbiter are the integration issue's (the engine here is
// private to the DRBG). No entropy or security claim (decision record 0008).
//
//   req_inst / req_reseed  one-cycle pulses: collect a seed from the sibling
//                          (gating rules: trng-interface.md 3.4), run the
//                          command, then clear the seed buffer.
//   req_gen + gen_bits     run a generate request directly (no seed needed).
//   done pulses when the requested sequence ends; err is the DRBG status
//   (0 ok, 1 not instantiated, 2 reseed required, 3 bad size). Blocks stream
//   on blk_*. A zeroize (reset, synchronized TRNG alarm, sw_zeroize) abandons
//   the sequence with no done.

module drbg_top #(
    parameter INST_WORDS      = 16,
    parameter RESEED_WORDS    = 8,
    parameter RESEED_INTERVAL = 65536
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         sw_zeroize,

    input  wire         req_inst,
    input  wire         req_reseed,
    input  wire         req_gen,
    input  wire [10:0]  gen_bits,
    output wire         busy,
    output wire         done,
    output wire [1:0]   err,
    output wire         seeded,
    output wire         reseed_required,
    output wire         alarm_zeroized,
    output wire         blk_valid,
    output wire         blk_last,
    output wire [127:0] blk_data,

    input  wire         trng_clk,
    input  wire [31:0]  trng_out_data,
    input  wire         trng_out_valid,
    input  wire         trng_gated,
    input  wire         trng_startup_done,
    input  wire         trng_alarm,
    output wire         trng_rst_n,
    output wire         trng_out_ready,
    output wire [3:0]   trng_bus_addr,
    output wire         trng_bus_we,
    output wire         trng_bus_re,
    output wire [31:0]  trng_bus_wdata
);

    localparam SEEDW = 32 * ((INST_WORDS > RESEED_WORDS) ? INST_WORDS : RESEED_WORDS);
    localparam [2:0] T_IDLE = 3'd0, T_COLLECT = 3'd1, T_CMD = 3'd2, T_RUN = 3'd3, T_REL = 3'd4;

    wire zeroize, seed_ready;
    wire [SEEDW-1:0] seed;
    wire d_done, d_busy;
    wire [1:0] d_err;

    reg [2:0] t_q;
    reg       reseed_q, gen_q, ack_q;
    reg [1:0] err_q;
    reg       done_q;
    reg       seed_req_q, release_q;
    reg       cmd_inst_q, cmd_reseed_q, cmd_gen_q;
    reg [10:0] gbits_q;

    assign busy = (t_q != T_IDLE);
    assign done = done_q;
    assign err  = err_q;

    always @(posedge clk) begin
        done_q       <= 1'b0;
        seed_req_q   <= 1'b0;
        release_q    <= 1'b0;
        cmd_inst_q   <= 1'b0;
        cmd_reseed_q <= 1'b0;
        cmd_gen_q    <= 1'b0;
        if (zeroize) begin
            t_q <= T_IDLE;
        end else case (t_q)
            T_IDLE: if (req_inst || req_reseed) begin
                reseed_q   <= !req_inst;
                gen_q      <= 1'b0;
                seed_req_q <= 1'b1;
                t_q        <= T_COLLECT;
            end else if (req_gen) begin
                gen_q     <= 1'b1;
                gbits_q   <= gen_bits;
                t_q       <= T_CMD;
            end
            T_COLLECT: if (seed_ready) t_q <= T_CMD;
            T_CMD: begin
                cmd_inst_q   <= !gen_q && !reseed_q;
                cmd_reseed_q <= !gen_q && reseed_q;
                cmd_gen_q    <= gen_q;
                t_q          <= T_RUN;
            end
            T_RUN: if (d_done) begin
                err_q <= d_err;
                if (gen_q) begin done_q <= 1'b1; t_q <= T_IDLE; end
                else begin release_q <= 1'b1; t_q <= T_REL; end
            end
            T_REL: begin done_q <= 1'b1; t_q <= T_IDLE; end
            default: t_q <= T_IDLE;
        endcase
    end

    trng_if #(.INST_WORDS(INST_WORDS), .RESEED_WORDS(RESEED_WORDS)) u_if (
        .clk(clk), .rst_n(rst_n), .sw_zeroize(sw_zeroize),
        .trng_clk(trng_clk), .trng_out_data(trng_out_data), .trng_out_valid(trng_out_valid),
        .trng_gated(trng_gated), .trng_startup_done(trng_startup_done), .trng_alarm(trng_alarm),
        .trng_rst_n(trng_rst_n), .trng_out_ready(trng_out_ready), .trng_bus_addr(trng_bus_addr),
        .trng_bus_we(trng_bus_we), .trng_bus_re(trng_bus_re), .trng_bus_wdata(trng_bus_wdata),
        .seed_req(seed_req_q), .seed_reseed(reseed_q), .seed_release(release_q),
        .seed_ready(seed_ready), .seed(seed), .zeroize(zeroize), .alarm_zeroized(alarm_zeroized));

    wire aes_start, aes_busy, aes_done;
    wire [127:0] aes_key, aes_block, aes_out;

    ctr_drbg #(.INST_WORDS(INST_WORDS), .RESEED_WORDS(RESEED_WORDS),
               .RESEED_INTERVAL(RESEED_INTERVAL)) u_drbg (
        .clk(clk), .zeroize(zeroize),
        .cmd_inst(cmd_inst_q), .cmd_reseed(cmd_reseed_q), .cmd_gen(cmd_gen_q),
        .gen_bits(gbits_q), .seed(seed),
        .busy(d_busy), .done(d_done), .err(d_err), .seeded(seeded), .reseed_required(reseed_required),
        .blk_valid(blk_valid), .blk_last(blk_last), .blk_data(blk_data),
        .aes_start(aes_start), .aes_key(aes_key), .aes_block(aes_block),
        .aes_busy(aes_busy), .aes_done(aes_done), .aes_out(aes_out));

    aes_core u_aes (.clk(clk), .zeroize(zeroize), .start(aes_start), .decrypt(1'b0),
                    .block_in(aes_block), .key_in(aes_key),
                    .busy(aes_busy), .done(aes_done), .block_out(aes_out));


endmodule
