// keyladder -- key ladder: 4 derived 256-bit slots, per-slot use-mask and lock,
// SP 800-108 counter-mode derivation over HMAC-SHA-256 (decision record 0003),
// write-only software key load, engine key release, zeroize.
//
// Scope: this block only (spec/target-spec.md section 3). No bus registers, no
// lifecycle FSM, no alarm synchronizer: `zeroize` is a plain synchronous input
// whose source (reset, ZEROIZE, synchronized alarm) is the top level's. The
// FORMAL properties are a sibling issue. This header makes no security or
// timing claim.
//
// KEY ISOLATION: slot contents leave the slot flops only through
//   - hmac_key[255:0]  (to an HMAC engine key input), nonzero only while
//                      hmac_req is high and the slot is valid with mask[2];
//   - aes_key[127:0]   (to the AES key port; slot[255:128]), nonzero only while
//                      aes_req is high and the slot is valid with mask[0]
//                      (aes_dec low) or mask[1] (aes_dec high);
//   - the key input of the internal HMAC used as the KDF PRF.
// No other output depends on slot contents. The release test is combinational
// on the mask at the time of use (P-5). A denied request raises `rel_deny`
// for one cycle and the key output stays zero. Locked slots may be released.
//
// Slot state per slot n (n = 0..3): sN (256-bit value), vN (valid), mN
// (use_mask[3:0]: [0] AES-enc, [1] AES-dec, [2] HMAC key, [3] KDF-parent),
// lN (lock), dN (chain depth, 2 bits). Depth: a slot derived from the root or
// loaded by software is 1, a slot derived from a slot of depth d is d+1;
// deriving from a depth-2 slot is refused (chain root -> slot -> slot).
//
// Commands (one-cycle pulses, accepted only while `busy` is low; more than one
// command in the same cycle is refused with E_BUSY):
//   cmd_derive  derive slot cmd_slot from the root key (cmd_parent_root = 1) or
//               slot cmd_parent, with use mask cmd_mask and the 32-byte
//               cmd_ctx (user_context), message per 0003:
//               00000001 || "ROT-SLOT" || 00 || parent_id || slot || mask ||
//               user_context || 00000100, parent_id = 0xFF for the root.
//               The result is written to the slot only when the HMAC finishes.
//   cmd_lock    set lock on cmd_slot (the slot must be valid).
//   ld_begin    start a software key load into cmd_slot with mask cmd_mask;
//               then eight ld_valid pulses carry the key as 32-bit words, most
//               significant word first. The slot is invalid until the eighth
//               word; a load abandoned midway leaves it invalid (zeroize to
//               recover). There is no readback of any kind.
// Rewriting a valid unlocked slot is allowed only with the same mask; any other
// mask is E_MASK_CHANGE (mask is immutable until zeroize). Deriving a slot from
// itself is refused (E_SELF).
//
// Refusals: err_pulse high for one cycle with err_code; no slot, mask, lock or
// depth changes. Codes: 1 E_LOCKED_DST, 2 E_PARENT_INVALID (parent not valid,
// i.e. never derived or zeroized, or locked), 3 E_NO_KDF_PARENT, 4
// E_MASK_CHANGE, 5 E_DEPTH, 6 E_BUSY, 7 E_ROOT_INVALID (root_key_valid low),
// 8 E_SELF, 9 E_LOCK_INVALID (lock of a slot that is not valid).
// done_pulse is high for one cycle when an accepted derive/lock/load completes.
//
// zeroize (highest priority, synchronous): clears every slot value, valid,
// mask, lock and depth, the captured derivation parameters (root-select,
// parent, destination, mask, ctx), the load counter, and aborts the
// sequencer with an HMAC `clear` (k0 and inner in hmac_sha256 are zeroed). A
// derivation in flight is dropped: no partial key is written. Limitation: the
// SHA-256 core datapath registers (w, hh, a..h) inside hmac_sha256 are not
// cleared by `clear` (rtl/sha256/sha256_core.v resets control only); this
// block cannot fix that and does not claim it.
//
// The key-bearing registers are exactly: s0..s3 (slot values), and the
// internal hmac_sha256 key/digest state. Control registers: v0..v3, m0..m3,
// l0..l3, d0..d3, state, cnt, par_root, par_sel, dst, mask_q, ctx_q.
//
// Synchronous active-low reset on all state.

module keyladder (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         zeroize,

    input  wire [255:0] root_key,
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
    input  wire [31:0]  ld_data,

    output wire         busy,
    output reg          done_pulse,
    output reg          err_pulse,
    output reg  [3:0]   err_code,
    output wire [3:0]   slot_valid,
    output wire [3:0]   slot_locked,

    input  wire         hmac_req,
    input  wire [1:0]   hmac_slot,
    output wire [255:0] hmac_key,

    input  wire         aes_req,
    input  wire         aes_dec,
    input  wire [1:0]   aes_slot,
    output wire [127:0] aes_key,

    output reg          rel_deny
);

    localparam [3:0] E_NONE = 4'd0, E_LOCKED_DST = 4'd1, E_PARENT_INVALID = 4'd2,
                     E_NO_KDF_PARENT = 4'd3, E_MASK_CHANGE = 4'd4, E_DEPTH = 4'd5,
                     E_BUSY = 4'd6, E_ROOT_INVALID = 4'd7, E_SELF = 4'd8,
                     E_LOCK_INVALID = 4'd9;

    localparam [2:0] S_IDLE = 3'd0,   // accepting commands
                     S_START = 3'd1,  // hmac start, key sampled
                     S_MSG = 3'd2,    // 52 message bytes into hmac
                     S_WAIT = 3'd3,   // wait for mac_valid
                     S_CLR = 3'd4,    // clear the hmac scratch after capture
                     S_LOAD = 3'd5;   // eight software key words

    // ---- slot storage (key-bearing: s0..s3) ----
    reg [255:0] s0, s1, s2, s3;
    reg         v0, v1, v2, v3;
    reg [3:0]   m0, m1, m2, m3;
    reg         l0, l1, l2, l3;
    reg [1:0]   d0, d1, d2, d3;

    // ---- sequencer ----
    reg [2:0]   state;
    reg [5:0]   cnt;
    reg         par_root;
    reg [1:0]   par_sel;
    reg [1:0]   dst;
    reg [3:0]   mask_q;
    reg [255:0] ctx_q;

    assign busy        = (state != S_IDLE);
    assign slot_valid  = {v3, v2, v1, v0};
    assign slot_locked = {l3, l2, l1, l0};

    function [255:0] sel_val;
        input [1:0] n;
        input [255:0] a0, a1, a2, a3;
        begin
            case (n)
                2'd0: sel_val = a0;
                2'd1: sel_val = a1;
                2'd2: sel_val = a2;
                default: sel_val = a3;
            endcase
        end
    endfunction
    function [3:0] sel4;
        input [1:0] n;
        input [3:0] a0, a1, a2, a3;
        begin
            case (n)
                2'd0: sel4 = a0;
                2'd1: sel4 = a1;
                2'd2: sel4 = a2;
                default: sel4 = a3;
            endcase
        end
    endfunction
    function [1:0] sel2;
        input [1:0] n;
        input [1:0] a0, a1, a2, a3;
        begin
            case (n)
                2'd0: sel2 = a0;
                2'd1: sel2 = a1;
                2'd2: sel2 = a2;
                default: sel2 = a3;
            endcase
        end
    endfunction

    // ---- engine key release ----
    wire [255:0] h_val = sel_val(hmac_slot, s0, s1, s2, s3);
    wire [3:0]   h_msk = sel4(hmac_slot, m0, m1, m2, m3);
    wire         h_vld = slot_valid[hmac_slot];
`ifdef KL_NEG_MASK
    // Negative control (a): the HMAC use-mask bit is not checked.
    wire         h_ok  = hmac_req && h_vld;
`else
    wire         h_ok  = hmac_req && h_vld && h_msk[2];
`endif
    assign hmac_key = h_ok ? h_val : 256'd0;

    wire [255:0] a_val = sel_val(aes_slot, s0, s1, s2, s3);
    wire [3:0]   a_msk = sel4(aes_slot, m0, m1, m2, m3);
    wire         a_vld = slot_valid[aes_slot];
    wire         a_ok  = aes_req && a_vld && (aes_dec ? a_msk[1] : a_msk[0]);
    assign aes_key = a_ok ? a_val[255:128] : 128'd0;

    // ---- internal PRF ----
    wire [255:0] p_val = sel_val(par_sel, s0, s1, s2, s3);
    wire [255:0] kin   = par_root ? root_key : p_val;

    wire        h_start = (state == S_START);
    wire        in_ready;
    wire [255:0] mac;
    wire        mac_valid;
    wire        h_busy;

    // message byte index 0..51
    wire [7:0] parent_id = par_root ? 8'hFF : {6'd0, par_sel};
    reg  [7:0] msg_byte;
    always @* begin
        if (cnt < 6'd4)       msg_byte = (cnt == 6'd3) ? 8'h01 : 8'h00;
        else if (cnt < 6'd12) msg_byte = "ROT-SLOT" >> (8 * (11 - cnt)) ;
        else if (cnt == 6'd12) msg_byte = 8'h00;
        else if (cnt == 6'd13) msg_byte = parent_id;
        else if (cnt == 6'd14) msg_byte = {6'd0, dst};
        else if (cnt == 6'd15) msg_byte = {4'd0, mask_q};
        else if (cnt < 6'd48)  msg_byte = ctx_q >> (8 * (47 - cnt));
        else                   msg_byte = (cnt == 6'd50) ? 8'h01 : 8'h00;
    end

    wire h_clear = zeroize || (state == S_CLR);

    hmac_sha256 prf (
        .clk(clk), .rst_n(rst_n),
        .clear(h_clear), .start(h_start),
        .key_long(1'b0), .key(kin), .key_len(6'd32),
        .lk_valid(1'b0), .lk_ready(), .lk_data(8'd0), .lk_last(1'b0), .lk_empty(1'b0),
        .in_valid(state == S_MSG), .in_ready(in_ready), .in_data(msg_byte),
        .in_last(cnt == 6'd51), .in_empty(1'b0),
        .mac(mac), .mac_valid(mac_valid), .busy(h_busy)
    );

    // ---- command decode ----
    wire [2:0] ncmd = {2'd0, cmd_derive} + {2'd0, cmd_lock} + {2'd0, ld_begin};
    wire any_cmd = (ncmd != 3'd0);

`ifdef KL_NEG_LOCK
    // Negative control (b): the lock bit is not checked on a write.
    wire        dst_locked = 1'b0;
`else
    wire        dst_locked = slot_locked[cmd_slot];
`endif
    wire        dst_valid  = slot_valid[cmd_slot];
    wire [3:0]  dst_mask   = sel4(cmd_slot, m0, m1, m2, m3);
    wire        mask_chg   = dst_valid && (dst_mask != cmd_mask);
    wire        p_vld      = slot_valid[cmd_parent];
    wire        p_lck      = slot_locked[cmd_parent];
    wire [3:0]  p_msk      = sel4(cmd_parent, m0, m1, m2, m3);
    wire [1:0]  p_dep      = sel2(cmd_parent, d0, d1, d2, d3);

    reg [3:0] chk;
    always @* begin
        chk = E_NONE;
        if (ncmd > 3'd1 || state != S_IDLE) chk = E_BUSY;
        else if (cmd_lock) begin
            if (!dst_valid) chk = E_LOCK_INVALID;
        end else begin
            if (dst_locked) chk = E_LOCKED_DST;
            else if (ld_begin) begin
                if (mask_chg) chk = E_MASK_CHANGE;
            end else if (cmd_parent_root) begin
                if (!root_key_valid) chk = E_ROOT_INVALID;
                else if (mask_chg) chk = E_MASK_CHANGE;
            end else begin
                if (!p_vld || p_lck) chk = E_PARENT_INVALID;
                else if (!p_msk[3]) chk = E_NO_KDF_PARENT;
                else if (p_dep >= 2'd2) chk = E_DEPTH;
                else if (cmd_parent == cmd_slot) chk = E_SELF;
                else if (mask_chg) chk = E_MASK_CHANGE;
            end
        end
    end
    wire accepted = any_cmd && (chk == E_NONE);

    wire [1:0] p_dep_now = par_root ? 2'd0 : sel2(par_sel, d0, d1, d2, d3);
    wire       ld_word   = (state == S_LOAD) && ld_valid;
    wire       mac_take  = (state == S_WAIT) && mac_valid;

    always @(posedge clk) begin
        if (!rst_n || zeroize) begin
            // Explicit zeroize list (P-10 review): every register below.
            s0 <= 256'd0; s1 <= 256'd0; s2 <= 256'd0;
            v0 <= 1'b0; v1 <= 1'b0; v2 <= 1'b0;
            m0 <= 4'd0; m1 <= 4'd0; m2 <= 4'd0;
            l0 <= 1'b0; l1 <= 1'b0; l2 <= 1'b0;
            d0 <= 2'd0; d1 <= 2'd0; d2 <= 2'd0;
`ifdef KL_NEG_ZEROIZE
            // Negative control (c): slot 3 is omitted from zeroize (reset only).
            if (!rst_n) begin
                s3 <= 256'd0; v3 <= 1'b0; m3 <= 4'd0; l3 <= 1'b0; d3 <= 2'd0;
            end
`else
            s3 <= 256'd0; v3 <= 1'b0; m3 <= 4'd0; l3 <= 1'b0; d3 <= 2'd0;
`endif
            state <= S_IDLE; cnt <= 6'd0;
            par_root <= 1'b0; par_sel <= 2'd0; dst <= 2'd0; mask_q <= 4'd0;
            ctx_q <= 256'd0;
            done_pulse <= 1'b0; err_pulse <= 1'b0; err_code <= E_NONE; rel_deny <= 1'b0;
        end else begin
            done_pulse <= 1'b0;
            err_pulse  <= 1'b0;
            err_code   <= E_NONE;
            rel_deny   <= (hmac_req && !h_ok) || (aes_req && !a_ok);

            if (any_cmd && chk != E_NONE) begin
                err_pulse <= 1'b1;
                err_code  <= chk;
            end

            case (state)
                S_IDLE: if (accepted) begin
                    if (cmd_lock) begin
                        case (cmd_slot)
                            2'd0: l0 <= 1'b1;
                            2'd1: l1 <= 1'b1;
                            2'd2: l2 <= 1'b1;
                            default: l3 <= 1'b1;
                        endcase
                        done_pulse <= 1'b1;
                    end else if (ld_begin) begin
                        dst <= cmd_slot; mask_q <= cmd_mask; cnt <= 6'd0;
                        case (cmd_slot)
                            2'd0: v0 <= 1'b0;
                            2'd1: v1 <= 1'b0;
                            2'd2: v2 <= 1'b0;
                            default: v3 <= 1'b0;
                        endcase
                        state <= S_LOAD;
                    end else begin
                        dst <= cmd_slot; mask_q <= cmd_mask; ctx_q <= cmd_ctx;
                        par_root <= cmd_parent_root; par_sel <= cmd_parent;
                        cnt <= 6'd0;
                        state <= S_START;
                    end
                end

                S_START: state <= S_MSG;

                S_MSG: if (in_ready) begin
                    cnt <= cnt + 6'd1;
                    if (cnt == 6'd51) state <= S_WAIT;
                end

                S_WAIT: if (mac_take) begin
                    case (dst)
                        2'd0: begin s0 <= mac; v0 <= 1'b1; m0 <= mask_q; d0 <= p_dep_now + 2'd1; end
                        2'd1: begin s1 <= mac; v1 <= 1'b1; m1 <= mask_q; d1 <= p_dep_now + 2'd1; end
                        2'd2: begin s2 <= mac; v2 <= 1'b1; m2 <= mask_q; d2 <= p_dep_now + 2'd1; end
                        default: begin s3 <= mac; v3 <= 1'b1; m3 <= mask_q; d3 <= p_dep_now + 2'd1; end
                    endcase
                    ctx_q <= 256'd0;
                    state <= S_CLR;
                end

                S_CLR: begin
                    done_pulse <= 1'b1;
                    state <= S_IDLE;
                end

                S_LOAD: if (ld_word) begin
                    case (dst)
                        2'd0: s0 <= {s0[223:0], ld_data};
                        2'd1: s1 <= {s1[223:0], ld_data};
                        2'd2: s2 <= {s2[223:0], ld_data};
                        default: s3 <= {s3[223:0], ld_data};
                    endcase
                    cnt <= cnt + 6'd1;
                    if (cnt == 6'd7) begin
                        case (dst)
                            2'd0: begin v0 <= 1'b1; m0 <= mask_q; d0 <= 2'd1; end
                            2'd1: begin v1 <= 1'b1; m1 <= mask_q; d1 <= 2'd1; end
                            2'd2: begin v2 <= 1'b1; m2 <= mask_q; d2 <= 2'd1; end
                            default: begin v3 <= 1'b1; m3 <= mask_q; d3 <= 2'd1; end
                        endcase
                        done_pulse <= 1'b1;
                        state <= S_IDLE;
                    end
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
