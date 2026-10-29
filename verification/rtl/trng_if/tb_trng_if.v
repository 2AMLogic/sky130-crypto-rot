// Bench wrapper: trng_if alone (INST 16 / RESEED 8 words), sibling pins are
// ports driven by the Python stub in trngmodel.py.
module tb_trng_if (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         sw_zeroize,
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
    output wire [31:0]  trng_bus_wdata,
    input  wire         seed_req,
    input  wire         seed_reseed,
    input  wire         seed_release,
    output wire         seed_ready,
    output wire [511:0] seed,
    output wire         zeroize,
    output wire         alarm_zeroized
);
    trng_if #(.INST_WORDS(16), .RESEED_WORDS(8)) u (.*);
endmodule
