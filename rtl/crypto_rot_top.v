// crypto_rot_top -- top level: the ratified register bus (0005), the register
// map (0009), the lifecycle/zeroize FSM of target-spec.md section 5, and the
// integration of aes_core, hmac_sha256, keyladder and drbg_top (which embeds
// trng_if). The sibling's RTL is not instantiated here; its pins pass through
// drbg_top and are ports of this block.
//
// KEY ISOLATION (the point of this block): the only host-visible values are
// control/status flags and the engine output windows AES_DOUT, HMAC_MAC and
// DRBG_OUT (P-4). No read mux input carries aes_key, hmac_key, a slot value,
// root_key, ld_data or a seed; the engine key ports are wired engine-to-ladder
// only and never reach a register (P-1, P-2). There is no debug path, no scan
// and no key readback of any kind (section 5, 0008).
//
// Bus (0005, 0009): Wishbone-classic-class slave, 32-bit, word-addressed,
// single-cycle handshake -- ack_o or err_o rises in the same cycle as
// cyc_i && stb_i and the master drops stb_i the next cycle. adr_i is a word
// address; any bit above [6] makes the access undefined (class 1). Violation
// classes (section 5): 1 undefined address, 2 write to a read-only register,
// 3 write while the addressed engine is busy (per the 0009 Gate column;
// HMAC_CTRL with only the CLEAR bit set is exempt), 4 read of a write-only
// location. Every refused access returns err_o with dat zero, sets the
// matching FAULT_CLS bit and the ERROR pending bit, and never reaches the
// engine.
//
// Operation model (section 5 escalation; this is the definition #87 states
// against the bus front end): an operation is the span in which an engine is
// busy, a key-load sequence is open, or an HMAC message word is being
// serialized. The first violation inside an operation sets FAULT status and
// is refused; a SECOND violation inside the same operation, or ANY violation
// while a key-load sequence is open, escalates: every key slot and the DRBG
// state are zeroized and STATE = FAULT_ZEROIZED until a software ZEROIZE.
// The engine command registers are AES_CTRL, HMAC_CTRL, HMAC_MSG_CTL,
// HMAC_MSG_DATA, KDF_CTRL, KEY_LOAD and DRBG_CTRL.
//
// Zeroize (section 5): the zeroize level ZR is asserted by reset (rs2 low),
// the synchronized TRNG alarm, the software ZEROIZE command (CTRL bit 0: a
// command, never stored) and the escalation above; the software and
// escalation pulses each hold ZR for three cycles so every block sees them.
// ZR drives keyladder.zeroize, aes_core.zeroize and drbg_top.sw_zeroize, and
// aborts any HMAC operation through its clear (which scrubs the SHA-256
// core). ZCAUSE records which event zeroized (reset / alarm / escalation /
// software); the W1C bits are host-cleared, not zeroize-cleared, so the
// record of an event survives it.
//
// Lifecycle FSM (section 5): RESET -> UNSEEDED (reset released) -> READY
// (DRBG seeded) -> RESEED_REQUIRED (interval hit, or TRNG gated while
// seeded) -> back to READY when seeded and no longer gated/refused.
// ALARM_ZEROIZED on the synchronized alarm, back to UNSEEDED when the sibling
// has cleared the alarm at its source (drbg_top's alarm_zeroized falls).
// FAULT_ZEROIZED on escalation; recovery is a software ZEROIZE -> UNSEEDED.
//
// Engine sequencing: an engine CTRL write with START first releases the slot
// key (the ladder's request pulse); one cycle later the engine start runs
// only if the ladder did not answer rel_deny -- a denied start never runs,
// and AES_STATUS/HMAC_STATUS.DENY (sticky until the next CTRL write) says
// so. If the engine went busy between the CTRL write and the decision cycle
// (a master issuing two CTRL writes on consecutive cycles), the start is
// suppressed and DENY latched: no block runs, and nothing is swallowed
// silently. The KDF command is a single-cycle decode of KDF_CTRL with
// cmd_ctx from the KDF_CTX words written before it; the key-load window is
// the ladder's own: KEY_LOAD is accepted only between LOAD_BEGIN and the
// eighth word. DRBG_CTRL decodes CMD 1/2/3 into the drbg_top request pulses;
// GEN_BITS above 128 is refused as ERR=3 without starting the core (0009
// Consequences). An HMAC message word written to HMAC_MSG_DATA is serialized
// most-significant-byte-first into the core's byte port; the latched
// HMAC_MSG_CTL (byte count, LAST, EMPTY) applies to the next word only and
// then returns to its default (four bytes, not last).
//
// Data words are big-endian throughout (0009): word 0 of a multi-word value
// is its most significant 32 bits.
//
// Negative controls (bench sensitivity, the same pattern as the blocks):
//   TOP_NEG_ZEROIZE  the zeroize level no longer reaches the key ladder
//                    (slots survive ZEROIZE; the zeroize tests must fail)
//   TOP_NEG_FAULT    an undefined-address access no longer records FAULT_CLS
//                    bit 0 (the fault tests must fail)
//
// No timing, entropy, side-channel or certification claim is made here
// (target-spec.md section 8, decision record 0008).

module crypto_rot_top (
    input  wire         clk,
    input  wire         rst_n,          // async assert, sync release

    // host register bus (0005)
    input  wire         cyc_i,
    input  wire         stb_i,
    input  wire         we_i,
    input  wire [15:0]  adr_i,
    input  wire [31:0]  dat_i,
    output wire [31:0]  dat_o,
    output wire         ack_o,
    output wire         err_o,
    output wire         irq_o,

    // root key input (0007): a flag and a value, never a bus readback
    input  wire [255:0] root_key,
    input  wire         root_key_valid,

    // sibling pins (trng-interface.md), through drbg_top
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

    // ------------------------------------------------------------------
    // reset synchronizer (same shape as trng_if)
    // ------------------------------------------------------------------
    reg rs1, rs2;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin rs1 <= 1'b0; rs2 <= 1'b0; end
        else        begin rs1 <= 1'b1; rs2 <= rs1;  end

    // ------------------------------------------------------------------
    // sibling pin mirrors for STATUS: gated and alarm are synchronized
    // (0009 STATUS layout); startup_done is a quasi-static mirror.
    // ------------------------------------------------------------------
    reg g1, g2;
    always @(posedge clk) begin g1 <= trng_gated; g2 <= g1; end
    wire gated_s2 = g2;
    reg a1, a2;
    always @(posedge clk) begin a1 <= trng_alarm; a2 <= a1; end
    wire alarm_s2 = a2;
    reg alarm_d;
    always @(posedge clk) alarm_d <= alarm_s2;
    wire alarm_ev = alarm_s2 & ~alarm_d;   // the alarm reached this domain

    // ------------------------------------------------------------------
    // engine pins (wires here, driven by the instantiations below)
    // ------------------------------------------------------------------
    wire         aes_busy, aes_done;
    wire [127:0] aes_blk;
    wire [127:0] aes_key;
    wire         hmac_busy, mac_valid, hmac_in_ready;
    wire [255:0] mac;
    wire [255:0] hmac_key;
    wire         kdf_busy, kdf_done_pulse, kdf_err_pulse;
    wire [3:0]   kdf_err_code;
    wire [3:0]   slot_valid, slot_locked;
    wire         rel_deny;
    wire         drbg_busy, drbg_done, drbg_seeded, drbg_reseed_required,
                 drbg_alarm_zeroized, drbg_blk_valid;
    wire [1:0]   drbg_err;
    wire [127:0] drbg_blk;

    // HMAC message serializer state (a FEED-gate and operation-window input)
    wire ser_active;

    // key-load window state (a KDF-LOAD-gate and escalation input)
    reg  load_seq_q;
    wire ld_wr_now;    // an accepted KEY_LOAD write this cycle

    // zeroize run-length: software ZEROIZE and escalation hold ZR 3 cycles
    reg  [1:0] zrun_q;
    wire       zr_pend = |zrun_q;
    wire       zr      = ~rs2 | alarm_s2 | zr_pend;

`ifdef TOP_NEG_ZEROIZE
    wire kl_zr = 1'b0;                 // negative control: the ladder survives
`else
    wire kl_zr = zr;
`endif

    // ------------------------------------------------------------------
    // bus decode (0009)
    // ------------------------------------------------------------------
    wire       sel = cyc_i & stb_i;
    wire       wr  = sel & we_i;
    wire       rd  = sel & ~we_i;
    wire       hi  = |adr_i[15:7];
    wire [6:0] a   = adr_i[6:0];

    wire d_status    = !hi & (a == 7'h00);
    wire d_ctrl      = !hi & (a == 7'h01);
    wire d_irq_mask  = !hi & (a == 7'h02);
    wire d_irq_pend  = !hi & (a == 7'h03);
    wire d_fault     = !hi & (a == 7'h04);
    wire d_zcause    = !hi & (a == 7'h05);
    wire d_aes_ctrl  = !hi & (a == 7'h10);
    wire d_aes_st    = !hi & (a == 7'h11);
    wire d_aes_din   = !hi & (a >= 7'h12) & (a <= 7'h15);
    wire d_aes_dout  = !hi & (a >= 7'h16) & (a <= 7'h19);
    wire d_hmac_ctrl = !hi & (a == 7'h20);
    wire d_hmac_st   = !hi & (a == 7'h21);
    wire d_msg_ctl   = !hi & (a == 7'h22);
    wire d_msg_data  = !hi & (a == 7'h23);
    wire d_hmac_mac  = !hi & (a >= 7'h28) & (a <= 7'h2F);
    wire d_kdf_ctrl  = !hi & (a == 7'h40);
    wire d_kdf_st    = !hi & (a == 7'h41);
    wire d_kdf_ctx   = !hi & (a >= 7'h44) & (a <= 7'h4B);
    wire d_key_load  = !hi & (a == 7'h4C);
    wire d_drbg_ctrl = !hi & (a == 7'h60);
    wire d_drbg_st   = !hi & (a == 7'h61);
    wire d_drbg_out  = !hi & (a >= 7'h62) & (a <= 7'h65);

    wire defined = d_status | d_ctrl | d_irq_mask | d_irq_pend | d_fault | d_zcause
                 | d_aes_ctrl | d_aes_st | d_aes_din | d_aes_dout
                 | d_hmac_ctrl | d_hmac_st | d_msg_ctl | d_msg_data | d_hmac_mac
                 | d_kdf_ctrl | d_kdf_st | d_kdf_ctx | d_key_load
                 | d_drbg_ctrl | d_drbg_st | d_drbg_out;
    wire acc_ro = d_status | d_aes_st | d_hmac_st | d_kdf_st | d_drbg_st
                | d_aes_dout | d_hmac_mac | d_drbg_out;
    wire acc_wo = d_ctrl | d_aes_ctrl | d_aes_din | d_hmac_ctrl | d_msg_ctl
                | d_msg_data | d_kdf_ctrl | d_kdf_ctx | d_key_load | d_drbg_ctrl;

    // ------------------------------------------------------------------
    // violation classes (0009 "Section 5 violation classes are decidable")
    // ------------------------------------------------------------------
    wire hmac_clear_only = wr & d_hmac_ctrl & dat_i[1] & ~dat_i[0];
    wire cls1 = sel & (hi | ~defined);
    wire cls2 = wr & defined & acc_ro;
    wire cls3 = (wr & d_aes_ctrl & aes_busy)
              | (wr & d_hmac_ctrl & hmac_busy & ~hmac_clear_only)
              | (wr & (d_msg_ctl | d_msg_data) & (ser_active | ~hmac_in_ready))
              | (wr & d_kdf_ctrl & kdf_busy)
              | (wr & d_kdf_ctx & kdf_busy)
              | (wr & d_key_load & ~(load_seq_q & kdf_busy))
              | (wr & d_drbg_ctrl & drbg_busy);
    wire cls4 = rd & defined & acc_wo;
`ifdef TOP_NEG_FAULT
    wire cls1_eff = 1'b0;              // negative control: class 1 unrecorded
`else
    wire cls1_eff = cls1;
`endif
    wire viol = cls1 | cls2 | cls3 | cls4;
    wire hit  = sel & ~viol;

    assign err_o = viol;
    assign ack_o = hit;

    // ------------------------------------------------------------------
    // operation window and escalation (see header)
    // ------------------------------------------------------------------
    wire eng_busy = aes_busy | hmac_busy | kdf_busy | drbg_busy;
    wire cmd_wr = hit & wr & (d_aes_ctrl | d_hmac_ctrl | d_kdf_ctrl | d_drbg_ctrl
                            | d_msg_ctl | d_msg_data | d_key_load);
    wire op_now = eng_busy | load_seq_q | ser_active | cmd_wr;
    reg  fault_q;                      // a violation inside the current operation
    wire escalate_now = viol & (fault_q | (load_seq_q & kdf_busy));
    always @(posedge clk or negedge rst_n)
        if (!rst_n)            fault_q <= 1'b0;
        else if (escalate_now) fault_q <= 1'b0;
        else if (!op_now)      fault_q <= 1'b0;
        else if (viol)         fault_q <= 1'b1;

    // software ZEROIZE (CTRL bit 0) and escalation pulses
    wire sw_zeroize_wr = hit & wr & d_ctrl & dat_i[0];
    always @(posedge clk or negedge rst_n)
        if (!rst_n)              zrun_q <= 2'd0;
        else if (sw_zeroize_wr || escalate_now) zrun_q <= 2'd3;
        else if (zr_pend)        zrun_q <= zrun_q - 2'd1;

    // ------------------------------------------------------------------
    // FAULT_CLS (0x04, W1C) and ZCAUSE (0x05, W1C)
    // ------------------------------------------------------------------
    reg [3:0] fault_cls_q;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) fault_cls_q <= 4'd0;
        else if (hit & wr & d_fault) fault_cls_q <= fault_cls_q & ~dat_i[3:0];
        else fault_cls_q <= fault_cls_q | {cls4, cls3, cls2, cls1_eff};

    reg [3:0] zcause_q;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) zcause_q <= 4'b0001;
        else if (hit & wr & d_zcause) zcause_q <= zcause_q & ~dat_i[3:0];
        else zcause_q <= zcause_q | {sw_zeroize_wr, escalate_now, alarm_ev, 1'b0};

    // ------------------------------------------------------------------
    // AES engine (public aes_core)
    // ------------------------------------------------------------------
    reg         aes_req_q, aes_dec_q, aes_done_s, aes_deny_s, aes_done_d;
    reg [1:0]   aes_slot_q;
    reg [127:0] aes_din_q;

    wire aes_start_wr = hit & wr & d_aes_ctrl & dat_i[0];
    wire aes_req      = aes_start_wr | aes_req_q;
    wire aes_dec      = aes_start_wr ? dat_i[1] : aes_dec_q;
    wire [1:0] aes_slot = aes_start_wr ? dat_i[5:4] : aes_slot_q;
    wire aes_denied   = aes_req_q & rel_deny;
    wire aes_swallow  = aes_req_q & ~rel_deny & aes_busy;   // see header
    wire aes_start    = aes_req_q & ~rel_deny & ~aes_busy;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            aes_req_q <= 1'b0; aes_dec_q <= 1'b0; aes_slot_q <= 2'd0;
            aes_done_s <= 1'b0; aes_deny_s <= 1'b0; aes_done_d <= 1'b0;
        end else begin
            aes_done_d <= aes_done;
            if (zr) begin
                aes_req_q  <= 1'b0;
                aes_done_s <= 1'b0;
                aes_deny_s <= 1'b0;
            end else if (aes_start_wr) begin
                aes_req_q  <= 1'b1;
                aes_dec_q  <= dat_i[1];
                aes_slot_q <= dat_i[5:4];
                aes_done_s <= 1'b0;
                aes_deny_s <= 1'b0;
            end else if (aes_req_q) begin
                aes_req_q <= 1'b0;
                if (aes_denied || aes_swallow) aes_deny_s <= 1'b1;
            end
            if (aes_done) aes_done_s <= 1'b1;
        end
    end

    wire aes_done_ev = aes_done & ~aes_done_d;

    // AES_DIN window (0x12-0x15, WO): word 0 is the most significant
    always @(posedge clk) begin
        if (zr) begin
            aes_din_q <= 128'd0;
        end else if (hit & wr & d_aes_din) begin
            case (a - 7'h12)
                2'd0: aes_din_q[127:96] <= dat_i;
                2'd1: aes_din_q[95:64]  <= dat_i;
                2'd2: aes_din_q[63:32]  <= dat_i;
                2'd3: aes_din_q[31:0]   <= dat_i;
            endcase
        end
    end

    aes_core u_aes (
        .clk(clk), .zeroize(zr),
        .start(aes_start), .decrypt(aes_dec),
        .block_in(aes_din_q), .key_in(aes_key),
        .busy(aes_busy), .done(aes_done), .block_out(aes_blk));

    // ------------------------------------------------------------------
    // HMAC engine (hmac_sha256; slot key only: key_long = 0, key_len = 32)
    // ------------------------------------------------------------------
    reg         hmac_req_q, hmac_deny_s, macv_d;
    reg [1:0]   hmac_slot_q;
    reg [1:0]   ctl_nb_q;          // bytes of the next word, minus one
    reg         ctl_last_q, ctl_empty_q;
    reg [31:0]  ser_wq;
    reg [1:0]   ser_iq;
    reg         ser_q;
    assign ser_active = ser_q;

    wire hmac_start_wr = hit & wr & d_hmac_ctrl & dat_i[0];
    wire hmac_clear_wr = hit & wr & d_hmac_ctrl & dat_i[1];
    wire hmac_req      = hmac_start_wr | hmac_req_q;
    wire [1:0] hmac_slot = hmac_start_wr ? dat_i[5:4] : hmac_slot_q;
    wire hmac_denied   = hmac_req_q & rel_deny;
    wire hmac_swallow  = hmac_req_q & ~rel_deny & hmac_busy;   // see header
    wire hmac_start    = hmac_req_q & ~rel_deny & ~hmac_busy;
    wire hmac_clear    = zr | hmac_clear_wr;

    wire feed_beat   = ser_q & hmac_in_ready;
    wire feed_last_i = ctl_empty_q ? (ser_iq == 2'd0) : (ser_iq == ctl_nb_q);
    wire hmac_in_valid = ser_q;
    wire [7:0] hmac_in_data  = ser_wq[31 - 8*ser_iq -: 8];
    wire hmac_in_last  = ser_q & ctl_last_q & feed_last_i;
    wire hmac_in_empty = ser_q & ctl_empty_q & ctl_last_q & (ser_iq == 2'd0);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            hmac_req_q <= 1'b0; hmac_slot_q <= 2'd0;
            hmac_deny_s <= 1'b0; macv_d <= 1'b0;
        end else begin
            macv_d <= mac_valid;
            if (zr) begin
                hmac_req_q  <= 1'b0;
                hmac_deny_s <= 1'b0;
            end else if (hmac_start_wr) begin
                hmac_req_q  <= 1'b1;
                hmac_slot_q <= dat_i[5:4];
                hmac_deny_s <= 1'b0;
            end else if (hmac_req_q) begin
                hmac_req_q <= 1'b0;
                if (hmac_denied || hmac_swallow) hmac_deny_s <= 1'b1;
            end
        end
    end

    wire macv_ev = mac_valid & ~macv_d;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ctl_nb_q <= 2'd3; ctl_last_q <= 1'b0; ctl_empty_q <= 1'b0;
            ser_q <= 1'b0; ser_iq <= 2'd0; ser_wq <= 32'd0;
        end else if (zr) begin
            ctl_nb_q <= 2'd3; ctl_last_q <= 1'b0; ctl_empty_q <= 1'b0;
            ser_q <= 1'b0; ser_iq <= 2'd0;
        end else begin
            if (hit & wr & d_msg_ctl) begin
                ctl_nb_q    <= dat_i[1:0];
                ctl_last_q  <= dat_i[2];
                ctl_empty_q <= dat_i[3];
            end
            if (hit & wr & d_msg_data) begin
                ser_q  <= 1'b1;
                ser_iq <= 2'd0;
                ser_wq <= dat_i;
            end else if (feed_beat) begin
                if (feed_last_i) begin
                    ser_q       <= 1'b0;
                    ctl_nb_q    <= 2'd3;      // the latch applies to one word
                    ctl_last_q  <= 1'b0;
                    ctl_empty_q <= 1'b0;
                end else begin
                    ser_iq <= ser_iq + 2'd1;
                end
            end
        end
    end

    hmac_sha256 u_hmac (
        .clk(clk), .rst_n(rst_n),
        .clear(hmac_clear), .start(hmac_start),
        .key_long(1'b0), .key(hmac_key), .key_len(6'd32),
        .lk_valid(1'b0), .lk_ready(), .lk_data(8'd0), .lk_last(1'b0), .lk_empty(1'b0),
        .in_valid(hmac_in_valid), .in_ready(hmac_in_ready),
        .in_data(hmac_in_data), .in_last(hmac_in_last), .in_empty(hmac_in_empty),
        .mac(mac), .mac_valid(mac_valid), .busy(hmac_busy));

    // ------------------------------------------------------------------
    // key ladder: command decode, ctx staging, key-load window, stickies
    // ------------------------------------------------------------------
    reg [255:0] ctx_q;
    reg         kdf_done_s, kdf_err_s;
    reg [3:0]   kdf_errc_s;

    wire kdf_ctrl_wr = hit & wr & d_kdf_ctrl;
    wire cmd_derive  = kdf_ctrl_wr & dat_i[0];
    wire cmd_lock    = kdf_ctrl_wr & dat_i[1];
    wire ld_begin    = kdf_ctrl_wr & dat_i[2];
    assign ld_wr_now = hit & wr & d_key_load;

    always @(posedge clk) begin
        if (zr) begin
            ctx_q <= 256'd0;
        end else if (hit & wr & d_kdf_ctx) begin
            ctx_q[255 - 32*(a - 7'h44) -: 32] <= dat_i;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            load_seq_q <= 1'b0;
            kdf_done_s <= 1'b0; kdf_err_s <= 1'b0; kdf_errc_s <= 4'd0;
        end else if (zr) begin
            load_seq_q <= 1'b0;
            kdf_done_s <= 1'b0; kdf_err_s <= 1'b0; kdf_errc_s <= 4'd0;
        end else begin
            if (kdf_ctrl_wr) begin
                load_seq_q <= ld_begin;
                kdf_done_s <= 1'b0;
                kdf_err_s  <= 1'b0;
                kdf_errc_s <= 4'd0;
            end else if (load_seq_q && !kdf_busy) begin
                load_seq_q <= 1'b0;
            end
            if (kdf_done_pulse) kdf_done_s <= 1'b1;
            if (kdf_err_pulse) begin
                kdf_err_s  <= 1'b1;
                kdf_errc_s <= kdf_err_code;
            end
        end
    end

    keyladder u_kdf (
        .clk(clk), .rst_n(rst_n), .zeroize(kl_zr),
        .root_key(root_key), .root_key_valid(root_key_valid),
        .cmd_derive(cmd_derive), .cmd_lock(cmd_lock), .ld_begin(ld_begin),
        .cmd_slot(kdf_ctrl_wr ? dat_i[5:4] : 2'd0),
        .cmd_parent_root(kdf_ctrl_wr ? dat_i[8] : 1'b0),
        .cmd_parent(kdf_ctrl_wr ? dat_i[13:12] : 2'd0),
        .cmd_mask(kdf_ctrl_wr ? dat_i[19:16] : 4'd0),
        .cmd_ctx(ctx_q),
        .ld_valid(ld_wr_now), .ld_data(dat_i),
        .busy(kdf_busy), .done_pulse(kdf_done_pulse), .err_pulse(kdf_err_pulse),
        .err_code(kdf_err_code), .slot_valid(slot_valid), .slot_locked(slot_locked),
        .hmac_req(hmac_req), .hmac_slot(hmac_slot), .hmac_key(hmac_key),
        .aes_req(aes_req), .aes_dec(aes_dec), .aes_slot(aes_slot), .aes_key(aes_key),
        .rel_deny(rel_deny));

    // ------------------------------------------------------------------
    // DRBG (drbg_top embeds trng_if and its own private AES engine)
    // ------------------------------------------------------------------
    reg        drbg_done_s, drbg_rej_q;
    reg [1:0]  drbg_err_s;

    wire drbg_ctrl_wr = hit & wr & d_drbg_ctrl;
    wire [1:0]  drbg_cmd  = dat_i[1:0];
    wire [10:0] drbg_genb = dat_i[26:16];
    wire drbg_reject  = drbg_ctrl_wr & (drbg_cmd == 2'd3) & (drbg_genb > 11'd128);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            drbg_done_s <= 1'b0; drbg_err_s <= 2'd0; drbg_rej_q <= 1'b0;
        end else if (zr) begin
            drbg_done_s <= 1'b0; drbg_err_s <= 2'd0; drbg_rej_q <= 1'b0;
        end else if (drbg_ctrl_wr) begin
            drbg_done_s <= drbg_reject;
            drbg_err_s  <= drbg_reject ? 2'd3 : 2'd0;
            drbg_rej_q  <= drbg_reject;
        end else if (drbg_done) begin
            drbg_done_s <= 1'b1;
            drbg_err_s  <= drbg_err;
        end
    end

    drbg_top #(.INST_WORDS(16), .RESEED_WORDS(8), .RESEED_INTERVAL(65536)) u_drbg (
        .clk(clk), .rst_n(rst_n), .sw_zeroize(zr),
        .req_inst(drbg_ctrl_wr & (drbg_cmd == 2'd1) & ~drbg_reject),
        .req_reseed(drbg_ctrl_wr & (drbg_cmd == 2'd2) & ~drbg_reject),
        .req_gen(drbg_ctrl_wr & (drbg_cmd == 2'd3) & ~drbg_reject),
        .gen_bits(drbg_genb),
        .busy(drbg_busy), .done(drbg_done), .err(drbg_err),
        .seeded(drbg_seeded), .reseed_required(drbg_reseed_required),
        .alarm_zeroized(drbg_alarm_zeroized),
        .blk_valid(drbg_blk_valid), .blk_last(), .blk_data(drbg_blk),
        .trng_clk(trng_clk), .trng_out_data(trng_out_data), .trng_out_valid(trng_out_valid),
        .trng_gated(trng_gated), .trng_startup_done(trng_startup_done), .trng_alarm(trng_alarm),
        .trng_rst_n(trng_rst_n), .trng_out_ready(trng_out_ready),
        .trng_bus_addr(trng_bus_addr), .trng_bus_we(trng_bus_we),
        .trng_bus_re(trng_bus_re), .trng_bus_wdata(trng_bus_wdata));

    // ------------------------------------------------------------------
    // lifecycle FSM (target-spec.md section 5)
    // ------------------------------------------------------------------
    localparam [2:0] ST_RESET = 3'd0, ST_UNSEEDED = 3'd1, ST_READY = 3'd2,
                     ST_RESEED_REQ = 3'd3, ST_ALARM_Z = 3'd4, ST_FAULT_Z = 3'd5;
    reg [2:0] state_q;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) state_q <= ST_RESET;
        else case (state_q)
            ST_RESET:      if (rs2) state_q <= ST_UNSEEDED;
            ST_UNSEEDED:   if (drbg_alarm_zeroized) state_q <= ST_ALARM_Z;
                           else if (escalate_now)   state_q <= ST_FAULT_Z;
                           else if (drbg_seeded && !alarm_s2) state_q <= ST_READY;
            ST_READY:      if (drbg_alarm_zeroized) state_q <= ST_ALARM_Z;
                           else if (escalate_now)   state_q <= ST_FAULT_Z;
                           else if ((drbg_reseed_required || (gated_s2 && drbg_seeded))
                                    && !alarm_s2) state_q <= ST_RESEED_REQ;
                           else if (!drbg_seeded && !alarm_s2) state_q <= ST_UNSEEDED;
            ST_RESEED_REQ: if (drbg_alarm_zeroized) state_q <= ST_ALARM_Z;
                           else if (escalate_now)   state_q <= ST_FAULT_Z;
                           else if (drbg_seeded && !drbg_reseed_required
                                    && !gated_s2 && !alarm_s2) state_q <= ST_READY;
            ST_ALARM_Z:    if (escalate_now) state_q <= ST_FAULT_Z;
                           else if (!drbg_alarm_zeroized && !alarm_s2)
                                                           state_q <= ST_UNSEEDED;
            ST_FAULT_Z:    if (sw_zeroize_wr) state_q <= ST_UNSEEDED;
            default:       state_q <= ST_RESET;
        endcase

    // ------------------------------------------------------------------
    // done / error events for IRQ_PEND (0009)
    // ------------------------------------------------------------------
    wire done_ev = aes_done_ev | macv_ev | kdf_done_pulse | drbg_done;
    wire err_ev  = viol | kdf_err_pulse | (drbg_done & (drbg_err != 2'd0))
                 | aes_denied | hmac_denied | drbg_reject;

    // ------------------------------------------------------------------
    // IRQ (0009): sticky DONE / ERROR / ALARM, single mask, level irq_o
    // ------------------------------------------------------------------
    reg irq_mask_q, irq_done_q, irq_err_q, irq_alarm_q;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin
            irq_mask_q <= 1'b0; irq_done_q <= 1'b0;
            irq_err_q <= 1'b0; irq_alarm_q <= 1'b0;
        end else if (hit & wr & d_irq_mask) begin
            irq_mask_q <= dat_i[0];
        end else if (hit & wr & d_irq_pend) begin
            if (dat_i[0]) irq_done_q  <= 1'b0;
            if (dat_i[1]) irq_err_q   <= 1'b0;
            if (dat_i[2]) irq_alarm_q <= 1'b0;
        end else begin
            if (done_ev)  irq_done_q  <= 1'b1;
            if (err_ev)   irq_err_q   <= 1'b1;
            if (alarm_ev) irq_alarm_q <= 1'b1;
        end
    assign irq_o = irq_mask_q & (irq_done_q | irq_err_q | irq_alarm_q);

    // ------------------------------------------------------------------
    // read mux (P-1/P-2 structure: only flags and engine output windows)
    // ------------------------------------------------------------------
    reg [31:0] rdata;
    always @* begin
        rdata = 32'd0;
        case (a)
            7'h00: rdata = {8'd0, slot_locked, slot_valid,
                            drbg_busy, kdf_busy, hmac_busy, aes_busy,
                            2'b00, root_key_valid, trng_startup_done,
                            alarm_s2, gated_s2, drbg_seeded,
                            (|fault_cls_q), eng_busy, state_q};
            7'h01: rdata = 32'd0;                    // WO: reads are class 4
            7'h02: rdata = {31'd0, irq_mask_q};
            7'h03: rdata = {29'd0, irq_alarm_q, irq_err_q, irq_done_q};
            7'h04: rdata = {28'd0, fault_cls_q};
            7'h05: rdata = {28'd0, zcause_q};
            7'h10: rdata = 32'd0;                    // WO
            7'h11: rdata = {29'd0, aes_deny_s, aes_done_s, aes_busy};
            7'h12: rdata = aes_din_q[127:96];        // WO: reads are class 4
            7'h13: rdata = aes_din_q[95:64];
            7'h14: rdata = aes_din_q[63:32];
            7'h15: rdata = aes_din_q[31:0];
            7'h16: rdata = aes_blk[127:96];
            7'h17: rdata = aes_blk[95:64];
            7'h18: rdata = aes_blk[63:32];
            7'h19: rdata = aes_blk[31:0];
            7'h20: rdata = 32'd0;                    // WO
            7'h21: rdata = {28'd0, hmac_deny_s, hmac_in_ready, mac_valid, hmac_busy};
            7'h22: rdata = 32'd0;                    // WO
            7'h23: rdata = 32'd0;                    // WO
            7'h28: rdata = mac[255:224];
            7'h29: rdata = mac[223:192];
            7'h2A: rdata = mac[191:160];
            7'h2B: rdata = mac[159:128];
            7'h2C: rdata = mac[127:96];
            7'h2D: rdata = mac[95:64];
            7'h2E: rdata = mac[63:32];
            7'h2F: rdata = mac[31:0];
            7'h40: rdata = 32'd0;                    // WO
            7'h41: rdata = {24'd0, kdf_errc_s, 1'b0, kdf_err_s, kdf_done_s, kdf_busy};
            7'h44, 7'h45, 7'h46, 7'h47,
            7'h48, 7'h49, 7'h4A, 7'h4B: rdata = 32'd0;   // WO
            7'h4C: rdata = 32'd0;                    // WO: reads are class 4
            7'h60: rdata = 32'd0;                    // WO
            7'h61: rdata = {24'd0, drbg_blk_valid,
                            drbg_alarm_zeroized, drbg_reseed_required, drbg_seeded,
                            drbg_err_s, drbg_done_s, drbg_busy};
            7'h62: rdata = drbg_blk[127:96];
            7'h63: rdata = drbg_blk[95:64];
            7'h64: rdata = drbg_blk[63:32];
            7'h65: rdata = drbg_blk[31:0];
            default: rdata = 32'd0;                  // undefined: class 1
        endcase
    end

    // a refused access returns zero, never data (0005/0009)
    assign dat_o = viol ? 32'd0 : rdata;

endmodule
