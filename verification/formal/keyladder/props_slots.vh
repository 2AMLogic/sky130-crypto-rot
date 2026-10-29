// props_slots.vh -- P-5 / P-6 property block for keyladder (issue #56).
//
// NOT compiled on its own. gen.py splices this text, unchanged, in front of the
// final `endmodule` of a COPY of rtl/keyladder/keyladder.v (RTL run) or of the
// keyladder module of the klt-synthesized netlist (netlist run). It reads only
// the module's ports and the register names s0..s3, v0..v3, m0..m3, l0..l3,
// d0..d3, state, dst, par_root, par_sel, which survive synthesis as named wires,
// so the same text is the property on both. Selected by -DP5 / -DP6 / -DCOVER.
//
// State encoding used below (keyladder.v): state 0 IDLE, 1 START, 2 MSG, 3 WAIT,
// 4 CLR, 5 LOAD.

    reg pf_init = 1'b1;           // true in the first cycle of a run only
    always @(posedge clk) pf_init <= 1'b0;
    // The first cycle of a run is the post-reset state: every register this block
    // names is at its reset value (the same values keyladder.v's reset assigns).
    // Registers outside this list (the HMAC/SHA-256 datapath) start free.
    always @* if (pf_init) begin
        assume(state == 3'd0 && dst == 2'd0 && par_root == 1'b0 && par_sel == 2'd0);
        assume(s0 == 256'd0 && s1 == 256'd0 && s2 == 256'd0 && s3 == 256'd0);
        assume(v0 == 1'b0 && v1 == 1'b0 && v2 == 1'b0 && v3 == 1'b0);
        assume(l0 == 1'b0 && l1 == 1'b0 && l2 == 1'b0 && l3 == 1'b0);
        assume(m0 == 4'd0 && m1 == 4'd0 && m2 == 4'd0 && m3 == 4'd0);
        assume(d0 == 2'd0 && d1 == 2'd0 && d2 == 2'd0 && d3 == 2'd0);
    end

    wire [3:0] pf_hm = (hmac_slot == 2'd0) ? m0 : (hmac_slot == 2'd1) ? m1 :
                       (hmac_slot == 2'd2) ? m2 : m3;
    wire [3:0] pf_am = (aes_slot  == 2'd0) ? m0 : (aes_slot  == 2'd1) ? m1 :
                       (aes_slot  == 2'd2) ? m2 : m3;
    wire [3:0] pf_pm = (par_sel == 2'd0) ? m0 : (par_sel == 2'd1) ? m1 :
                       (par_sel == 2'd2) ? m2 : m3;
    wire       pf_pv = (par_sel == 2'd0) ? v0 : (par_sel == 2'd1) ? v1 :
                       (par_sel == 2'd2) ? v2 : v3;
    wire       pf_hv = slot_valid[hmac_slot];
    wire       pf_av = slot_valid[aes_slot];
    wire       pf_dl = (dst == 2'd0) ? l0 : (dst == 2'd1) ? l1 : (dst == 2'd2) ? l2 : l3;

`ifdef P5
    // P-5: a slot is used only by an engine whose use-mask bit is set, at the time
    // of use. "Use" is (a) the HMAC key output, (b) the AES key output, (c) the
    // internal KDF PRF key input (a slot parent), sampled in the START state.
    always @* begin
        if (hmac_key != 256'd0)
            assert(hmac_req && pf_hv && pf_hm[2]);
        if (aes_key != 128'd0)
            assert(aes_req && pf_av && (aes_dec ? pf_am[1] : pf_am[0]));
        if (state == 3'd1 && !par_root)
            assert(pf_pv && pf_pm[3]);
    end
`endif

`ifdef P6
    // P-6: a locked slot cannot be written and its mask cannot change until
    // zeroize/reset. Transition form over registered copies of the previous cycle.
    reg         pf_hp = 1'b0;      // previous-cycle copies are meaningful
    reg         pf_pclr = 1'b0;    // zeroize or reset was applied at the previous edge
    reg [255:0] pf_s0, pf_s1, pf_s2, pf_s3;
    reg [3:0]   pf_m0, pf_m1, pf_m2, pf_m3;
    reg [1:0]   pf_d0, pf_d1, pf_d2, pf_d3;
    reg         pf_v0, pf_v1, pf_v2, pf_v3;
    reg         pf_l0, pf_l1, pf_l2, pf_l3;
    always @(posedge clk) begin
        pf_hp <= 1'b1;
        pf_pclr <= zeroize || !rst_n;
        pf_s0 <= s0; pf_s1 <= s1; pf_s2 <= s2; pf_s3 <= s3;
        pf_m0 <= m0; pf_m1 <= m1; pf_m2 <= m2; pf_m3 <= m3;
        pf_d0 <= d0; pf_d1 <= d1; pf_d2 <= d2; pf_d3 <= d3;
        pf_v0 <= v0; pf_v1 <= v1; pf_v2 <= v2; pf_v3 <= v3;
        pf_l0 <= l0; pf_l1 <= l1; pf_l2 <= l2; pf_l3 <= l3;
    end
    wire pf_live = pf_hp && !pf_pclr;
    always @* begin
        if (pf_live && pf_l0) assert(l0 && v0 && s0 == pf_s0 && m0 == pf_m0 && d0 == pf_d0);
        if (pf_live && pf_l1) assert(l1 && v1 && s1 == pf_s1 && m1 == pf_m1 && d1 == pf_d1);
        if (pf_live && pf_l2) assert(l2 && v2 && s2 == pf_s2 && m2 == pf_m2 && d2 == pf_d2);
        if (pf_live && pf_l3) assert(l3 && v3 && s3 == pf_s3 && m3 == pf_m3 && d3 == pf_d3);
        // Strengthening invariants (written in the record):
        //   I1  the sequencer state is one of the six defined states;
        //   I2  while a derivation or load is in flight, its destination is not locked
        //       (a lock is only accepted in IDLE, a write only into an unlocked slot);
        //   I3  a lock implies the slot is valid (a lock is only accepted on a valid
        //       slot; a valid bit is cleared only for an unlocked slot or by zeroize).
        assert(state <= 3'd5);
        if (state != 3'd0) assert(!pf_dl);
        assert(!l0 || v0);
        assert(!l1 || v1);
        assert(!l2 || v2);
        assert(!l3 || v3);
    end
`endif

`ifdef COVER
    // Non-vacuity: the interesting states are reachable in the run.
    reg pf_hp = 1'b0; reg pf_pl0 = 1'b0;
    always @(posedge clk) begin pf_hp <= 1'b1; pf_pl0 <= l0; end
    always @* begin
        cover(state == 3'd1 && !par_root);                 // slot-parent derivation started
        cover(state == 3'd1 && par_root);                  // root derivation started
        cover(state == 3'd4);                              // derivation captured
        cover(pf_hp && !pf_pl0 && l0);                     // a lock set
        cover(err_pulse && err_code == 4'd1);              // write to a locked slot refused
        cover(err_pulse && err_code == 4'd4);              // mask change refused
        cover(hmac_key != 256'd0);                         // HMAC release granted
        cover(aes_key != 128'd0 && aes_dec);               // AES decrypt release granted
        cover(aes_key != 128'd0 && !aes_dec);              // AES encrypt release granted
        cover(rel_deny);                                   // release denied
        cover(done_pulse && state == 3'd0 && l0);          // operation done with a locked slot 0
    end
`endif
