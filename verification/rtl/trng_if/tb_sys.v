// Bench wrapper: drbg_top (trng_if + ctr_drbg + aes_core). Default: sibling
// pins are ports driven by the Python stub (trngmodel.py), reseed interval 3
// so RESEED_REQUIRED is reachable. With REAL_TRNG the pinned sibling
// trng_digital is instantiated (fetched at its pin by fetch_trng.sh; its
// start-up length and conditioner block are shortened by parameter so the
// bench finishes, which changes no behavior this block depends on) and only
// raw_bit/raw_valid are driven from outside.
`ifdef REAL_TRNG
`define SYS_INT 65536
`else
`define SYS_INT 3
`endif
module tb_sys (
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
`ifdef REAL_TRNG
    input  wire         raw_bit,
    input  wire         raw_valid,
    output wire [31:0]  trng_out_data,
    output wire         trng_out_valid,
    output wire         trng_gated,
    output wire         trng_startup_done,
    output wire         trng_alarm,
`else
    input  wire [31:0]  trng_out_data,
    input  wire         trng_out_valid,
    input  wire         trng_gated,
    input  wire         trng_startup_done,
    input  wire         trng_alarm,
`endif
    output wire         trng_rst_n,
    output wire         trng_out_ready,
    output wire [3:0]   trng_bus_addr,
    output wire         trng_bus_we,
    output wire         trng_bus_re,
    output wire [31:0]  trng_bus_wdata
);
    drbg_top #(.INST_WORDS(16), .RESEED_WORDS(8), .RESEED_INTERVAL(`SYS_INT)) u (.*);
`ifdef REAL_TRNG
    trng_digital #(.C_RCT(16), .STARTUP(16), .COND_BITS(64)) sib (
        .clk(trng_clk), .rst_n(trng_rst_n), .raw_bit(raw_bit), .raw_valid(raw_valid),
        .bus_addr(trng_bus_addr), .bus_we(trng_bus_we), .bus_re(trng_bus_re),
        .bus_wdata(trng_bus_wdata), .bus_rdata(),
        .out_data(trng_out_data), .out_valid(trng_out_valid), .out_ready(trng_out_ready),
        .alarm(trng_alarm), .gated(trng_gated), .startup_done(trng_startup_done));
`endif
endmodule
