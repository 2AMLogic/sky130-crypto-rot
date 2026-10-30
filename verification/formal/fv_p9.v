// Formal wrapper for P-9: a synchronized TRNG alarm zeroizes the DRBG
// Key/V and working registers, the seed buffer and the sibling out_ready
// strobe within two core cycles of the synchronizer output, and holds them
// zero while the alarm is asserted.
//
// Composition: trng_if (real RTL, with its 2-flop alarm synchronizer modelled
// as an ordinary register chain at the core clock; clock-domain timing itself
// is not proven) + ctr_drbg (real RTL) + the abstract AES handshake of
// fv_drbg.v. Sibling pins, commands and seed requests are free. The AES core's
// own zeroize (#43) and key slots (#44/#46) are not in this composition.
//
// Property: if the synchronized alarm was high two cycles ago, every
// key-bearing and working register named by the modules' fv_zero is zero now.
// Stated that way it covers single-cycle alarm pulses (the response is not
// conditional on the alarm staying high) and, evaluated every cycle, holding
// zero while the alarm stays asserted.
module fv_p9 (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         sw_zeroize,
    input  wire         trng_clk,
    input  wire [31:0]  trng_out_data,
    input  wire         trng_out_valid,
    input  wire         trng_gated,
    input  wire         trng_startup_done,
    input  wire         trng_alarm,
    input  wire         seed_req,
    input  wire         seed_reseed,
    input  wire         seed_release,
    input  wire         cmd_inst,
    input  wire         cmd_reseed,
    input  wire         cmd_gen,
    input  wire [10:0]  gen_bits,
    input  wire         fv_finish,
    input  wire [127:0] fv_out
);
    reg f_init = 1'b1;
    always @(posedge clk) f_init <= 1'b0;
    always @* if (f_init) assume (!rst_n);

    wire zeroize, seed_ready, alarm_zeroized, if_zero, if_a2, drbg_zero;
    wire [511:0] seed;
    wire trng_rst_n, trng_out_ready, trng_bus_we, trng_bus_re;
    wire [3:0] trng_bus_addr;
    wire [31:0] trng_bus_wdata;

    trng_if #(.INST_WORDS(16), .RESEED_WORDS(8)) u_if (
        .fv_zero(if_zero), .fv_alarm_s2(if_a2),
        .clk(clk), .rst_n(rst_n), .sw_zeroize(sw_zeroize),
        .trng_clk(trng_clk), .trng_out_data(trng_out_data), .trng_out_valid(trng_out_valid),
        .trng_gated(trng_gated), .trng_startup_done(trng_startup_done), .trng_alarm(trng_alarm),
        .trng_rst_n(trng_rst_n), .trng_out_ready(trng_out_ready), .trng_bus_addr(trng_bus_addr),
        .trng_bus_we(trng_bus_we), .trng_bus_re(trng_bus_re), .trng_bus_wdata(trng_bus_wdata),
        .seed_req(seed_req), .seed_reseed(seed_reseed), .seed_release(seed_release),
        .seed_ready(seed_ready), .seed(seed), .zeroize(zeroize), .alarm_zeroized(alarm_zeroized));

    wire busy, done, seeded, reseed_required, blk_valid, blk_last, aes_start;
    wire [1:0] err;
    wire [127:0] blk_data, aes_key, aes_block;
    reg eng_busy = 1'b0, eng_done = 1'b0;
    wire [127:0] aes_out = eng_done ? fv_out : 128'd0;
    always @(posedge clk) begin
        if (zeroize) begin eng_busy <= 1'b0; eng_done <= 1'b0; end
        else if (aes_start && !eng_busy) begin eng_busy <= 1'b1; eng_done <= 1'b0; end
        else if (eng_busy && fv_finish) begin eng_busy <= 1'b0; eng_done <= 1'b1; end
    end

    ctr_drbg #(.INST_WORDS(16), .RESEED_WORDS(8), .RESEED_INTERVAL(65536)) u_drbg (
        .fv_zero(drbg_zero),
        .clk(clk), .zeroize(zeroize), .cmd_inst(cmd_inst), .cmd_reseed(cmd_reseed),
        .cmd_gen(cmd_gen), .gen_bits(gen_bits), .seed(seed),
        .busy(busy), .done(done), .err(err), .seeded(seeded), .reseed_required(reseed_required),
        .blk_valid(blk_valid), .blk_last(blk_last), .blk_data(blk_data),
        .aes_start(aes_start), .aes_key(aes_key), .aes_block(aes_block),
        .aes_busy(eng_busy), .aes_done(eng_done), .aes_out(aes_out));

    reg h1 = 1'b0, h2 = 1'b0;
    always @(posedge clk) begin h1 <= if_a2; h2 <= h1; end

`ifdef P9_NEG_BOUND
    // negative control: claim the response one cycle too early; must FAIL
    always @* assert (!h1 || (if_zero && drbg_zero));
`else
    always @* assert (!h2 || (if_zero && drbg_zero));
`endif
`ifdef REACH_NONZERO
    // vacuity: the registers can hold non-zero state at all; must FAIL
    always @* if (!f_init) assert (if_zero && drbg_zero);
`endif
endmodule
