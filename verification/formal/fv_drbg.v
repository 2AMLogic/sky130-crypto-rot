// Formal wrapper for P-7 and P-8 on rtl/drbg/ctr_drbg.v.
//
// The properties themselves are inside ctr_drbg.v under `ifdef FORMAL (they
// refer to its registers). This wrapper supplies the environment: every
// command, size and seed input is free; the AES engine is abstracted as a
// handshake that accepts a start when idle and completes after an
// unconstrained latency of at least one cycle with an unconstrained result
// (aes_core.v's busy/done contract, without its datapath). The abstraction is
// sound for these control properties because the DRBG's gating decisions never
// read the AES result. zeroize is free (the claim holds for any zeroize
// pattern) but is asserted in the first cycle: there is no reset.
//
// REACH builds the vacuity checks: the same environment with an assertion
// that the output stream is never valid, which must FAIL (a counterexample is
// a witness that blk_valid is reachable).
module fv_drbg (
    input  wire         clk,
    input  wire         zeroize_free,
    input  wire         cmd_inst,
    input  wire         cmd_reseed,
    input  wire         cmd_gen,
    input  wire [10:0]  gen_bits,
    input  wire [511:0] seed,
    input  wire         fv_finish,
    input  wire [127:0] fv_out
);
`ifdef REACH_INTERVAL
    localparam INTERVAL = 1;
`else
    localparam INTERVAL = 65536;
`endif
    reg f_init = 1'b1;
    always @(posedge clk) f_init <= 1'b0;
    wire zeroize = zeroize_free | f_init;

    wire busy, done, seeded, reseed_required, blk_valid, blk_last;
    wire [1:0] err;
    wire [127:0] blk_data;
    wire aes_start;
    wire [127:0] aes_key, aes_block;
    reg eng_busy = 1'b0, eng_done = 1'b0;
    wire [127:0] aes_out = eng_done ? fv_out : 128'd0;

    always @(posedge clk) begin
        if (zeroize) begin
            eng_busy <= 1'b0;
            eng_done <= 1'b0;
        end else if (aes_start && !eng_busy) begin
            eng_busy <= 1'b1;
            eng_done <= 1'b0;
        end else if (eng_busy && fv_finish) begin
            eng_busy <= 1'b0;
            eng_done <= 1'b1;
        end
    end

    ctr_drbg #(.INST_WORDS(16), .RESEED_WORDS(8), .RESEED_INTERVAL(INTERVAL)) dut (
        .fv_zero(),
        .clk(clk), .zeroize(zeroize), .cmd_inst(cmd_inst), .cmd_reseed(cmd_reseed),
        .cmd_gen(cmd_gen), .gen_bits(gen_bits), .seed(seed),
        .busy(busy), .done(done), .err(err), .seeded(seeded), .reseed_required(reseed_required),
        .blk_valid(blk_valid), .blk_last(blk_last), .blk_data(blk_data),
        .aes_start(aes_start), .aes_key(aes_key), .aes_block(aes_block),
        .aes_busy(eng_busy), .aes_done(eng_done), .aes_out(aes_out));

`ifdef REACH_VALID
    always @* if (!f_init) assert (!blk_valid);
`endif
`ifdef REACH_OVER
    always @* if (!f_init) assert (!reseed_required);
`endif
endmodule
