// Bench wrapper: crypto_rot_top (bus + register file + lifecycle FSM +
// aes_core + hmac_sha256 + keyladder + drbg_top/trng_if). All ports pass
// through: the bus, root_key and the sibling pins are driven/read from Python
// (test_crypto_rot_top.py; the sibling pins by the port-protocol stub in
// verification/rtl/trng_if/trngmodel.py, as tb_sys.v does).

module tb_top (
    input  wire         clk,
    input  wire         rst_n,

    input  wire         cyc_i,
    input  wire         stb_i,
    input  wire         we_i,
    input  wire [15:0]  adr_i,
    input  wire [31:0]  dat_i,
    output wire [31:0]  dat_o,
    output wire         ack_o,
    output wire         err_o,
    output wire         irq_o,

    input  wire [255:0] root_key,
    input  wire         root_key_valid,

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
    crypto_rot_top u (.*);
endmodule
