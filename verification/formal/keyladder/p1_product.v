// p1_product.v -- module-boundary P-1 (issue #56): 2-trace non-interference.
//
// Two copies of keyladder get identical values on every input except the key
// material: the root key and the software-load words (ld_data). cmd_ctx is the
// 0003 user_context, a public label, and is shared. Asserted: every output other
// than the two key-bearing ones (hmac_key, aes_key) is equal in both copies at
// every cycle. Registers without a reset (the SHA-256 core datapath) start free
// and independent in each copy, so "differ only in key material" includes any
// residue in them. The first cycle is a reset.
//
// This is the MODULE-boundary property; the bus-level P-1 (dat_o/ack/err/irq) needs
// the bus front end and is issue #46's.
module p1_top (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         zeroize,
    input  wire         root_key_valid,
    input  wire         cmd_derive,
    input  wire         cmd_lock,
    input  wire         ld_begin,
    input  wire [1:0]   cmd_slot,
    input  wire         cmd_parent_root,
    input  wire [1:0]   cmd_parent,
    input  wire [3:0]   cmd_mask,
    input  wire [255:0] cmd_ctx,
    input  wire         ld_valid,
    input  wire         hmac_req,
    input  wire [1:0]   hmac_slot,
    input  wire         aes_req,
    input  wire         aes_dec,
    input  wire [1:0]   aes_slot,
    // key material, independent per copy
    input  wire [255:0] root_key_a,
    input  wire [255:0] root_key_b,
    input  wire [31:0]  ld_data_a,
    input  wire [31:0]  ld_data_b
);
    wire         busy_a, busy_b, done_a, done_b, errp_a, errp_b, deny_a, deny_b;
    wire [3:0]   errc_a, errc_b, sv_a, sv_b, sl_a, sl_b;
    wire [255:0] hk_a, hk_b;
    wire [127:0] ak_a, ak_b;

    keyladder ka (
        .clk(clk), .rst_n(rst_n), .zeroize(zeroize),
        .root_key(root_key_a), .root_key_valid(root_key_valid),
        .cmd_derive(cmd_derive), .cmd_lock(cmd_lock), .ld_begin(ld_begin),
        .cmd_slot(cmd_slot), .cmd_parent_root(cmd_parent_root), .cmd_parent(cmd_parent),
        .cmd_mask(cmd_mask), .cmd_ctx(cmd_ctx), .ld_valid(ld_valid), .ld_data(ld_data_a),
        .busy(busy_a), .done_pulse(done_a), .err_pulse(errp_a), .err_code(errc_a),
        .slot_valid(sv_a), .slot_locked(sl_a),
        .hmac_req(hmac_req), .hmac_slot(hmac_slot), .hmac_key(hk_a),
        .aes_req(aes_req), .aes_dec(aes_dec), .aes_slot(aes_slot), .aes_key(ak_a),
        .rel_deny(deny_a));
    keyladder kb (
        .clk(clk), .rst_n(rst_n), .zeroize(zeroize),
        .root_key(root_key_b), .root_key_valid(root_key_valid),
        .cmd_derive(cmd_derive), .cmd_lock(cmd_lock), .ld_begin(ld_begin),
        .cmd_slot(cmd_slot), .cmd_parent_root(cmd_parent_root), .cmd_parent(cmd_parent),
        .cmd_mask(cmd_mask), .cmd_ctx(cmd_ctx), .ld_valid(ld_valid), .ld_data(ld_data_b),
        .busy(busy_b), .done_pulse(done_b), .err_pulse(errp_b), .err_code(errc_b),
        .slot_valid(sv_b), .slot_locked(sl_b),
        .hmac_req(hmac_req), .hmac_slot(hmac_slot), .hmac_key(hk_b),
        .aes_req(aes_req), .aes_dec(aes_dec), .aes_slot(aes_slot), .aes_key(ak_b),
        .rel_deny(deny_b));

    reg pf_init = 1'b1;
    always @(posedge clk) pf_init <= 1'b0;
    always @* if (pf_init) assume(!rst_n);

    wire nonkey_eq = (busy_a == busy_b) && (done_a == done_b) && (errp_a == errp_b) &&
                     (errc_a == errc_b) && (sv_a == sv_b) && (sl_a == sl_b) &&
                     (deny_a == deny_b);
`ifdef P1
    // Cycle 0 is before the first reset edge: the two copies' control registers are
    // independent garbage there, so the comparison starts at cycle 1.
    always @* if (!pf_init) assert(nonkey_eq);
`endif
`ifdef COVER
    // Non-vacuity: the two copies' key outputs genuinely differ while the check holds.
    // Gated past cycle 0 (before the first reset edge the registers are free).
    always @* if (!pf_init) begin
        cover(hk_a != hk_b);
        cover(ak_a != ak_b);
        cover(busy_a && busy_b);
        cover(done_a && done_b);
    end
`endif
endmodule
