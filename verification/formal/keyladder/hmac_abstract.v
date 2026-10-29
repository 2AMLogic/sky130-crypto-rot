// hmac_abstract.v -- formal-only stand-in for rtl/hmac/hmac_sha256.v (issue #56).
//
// Every output is an unconstrained per-cycle input (anyseq), so any behaviour of
// the real core is a behaviour of this module. Used ONLY for the slot properties
// P-5 and P-6, which are statements about the ladder's own registers and are
// independent of the HMAC datapath; a proof over this abstraction holds for the
// real core as well. NOT used for P-1 or P-2, which run on the real core.
module hmac_sha256 (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         clear,
    input  wire         start,
    input  wire         key_long,
    input  wire [255:0] key,
    input  wire [5:0]   key_len,
    input  wire         lk_valid,
    output wire         lk_ready,
    input  wire [7:0]   lk_data,
    input  wire         lk_last,
    input  wire         lk_empty,
    input  wire         in_valid,
    output wire         in_ready,
    input  wire [7:0]   in_data,
    input  wire         in_last,
    input  wire         in_empty,
    output wire [255:0] mac,
    output wire         mac_valid,
    output wire         busy
);
    (* anyseq *) wire         a_lk_ready;
    (* anyseq *) wire         a_in_ready;
    (* anyseq *) wire [255:0] a_mac;
    (* anyseq *) wire         a_mac_valid;
    (* anyseq *) wire         a_busy;
    assign lk_ready  = a_lk_ready;
    assign in_ready  = a_in_ready;
    assign mac       = a_mac;
    assign mac_valid = a_mac_valid;
    assign busy      = a_busy;
endmodule
