// hmac_sha256 -- HMAC-SHA-256 (RFC 2104 / FIPS 198-1) around one sha256_core.
//
// Scope: the HMAC sequencer only. No bus interface, no key slots, no use-masks,
// no zeroize policy (those belong to the key ladder). Byte-oriented messages.
//
// Sequence (one operation, started by a one-cycle `start` while idle):
//   1. K0: the key padded with zeros to the 64-byte block, or SHA-256(key)
//      padded, when the key is longer than a block.
//   2. inner hash: ipad block (K0 ^ 0x36..), the message, padding (in core).
//   3. outer hash: opad block (K0 ^ 0x5c..), the 32-byte inner digest.
//   4. mac_valid rises with mac = the outer digest.
//
// Key input, chosen by `key_long`, sampled on the `start` cycle:
//   key_long = 0  slot key: key[255:0] with key_len (0..32, larger counts as
//                 32). Byte 0 is key[255:248]; bytes at or beyond key_len are
//                 forced to zero. Only `start` samples key / key_len.
//   key_long = 1  byte stream on lk_valid/lk_ready/lk_data/lk_last/lk_empty,
//                 the same shape as the message stream (lk_empty with lk_last
//                 ends the key without a data byte). Any length. A key of at
//                 most 64 bytes is used as is; a longer key is hashed to K0.
//                 This port exists so that keys longer than 32 bytes (RFC 4231
//                 cases 6 and 7 use 131 bytes) run against the RTL.
// The key inputs are write-only: no output depends on them except through
// `mac`. The sequencer stores K0 in a 64-byte register `k0` and the inner
// digest in `inner`; neither is visible at a port.
//
// Message input: in_valid/in_ready/in_data/in_last/in_empty exactly as
// sha256_core. in_ready is high only in the message phase of an operation.
//
// Outputs: mac[255:0] is the full 32-byte tag, valid while mac_valid is high
// (zero otherwise). mac_valid clears on the next `start`. busy is high from
// the accepted `start` until mac_valid rises.
//
// clear: while high for a cycle, aborts any operation (sequencer and hash core
// control state return to idle), zeroes k0 and inner and drops mac_valid. A
// `start` in the same cycle is ignored.
//
// Cost: the hash work for the KDF message shape (52-byte message, key of at
// most 64 bytes) is 4 compressions (260 core cycles). The sequencer feeds the
// ipad and opad blocks, and the inner digest, one byte per cycle through the
// core's byte-serial port, so the total from `start` to mac_valid is more; the
// bench measures it.
//
// Synchronous active-low reset on all state, including k0 and inner.

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

`ifdef HMAC_NEG_CTRL
    // Negative control: one bit of the opad constant flipped (0x5c -> 0x5d).
    localparam [7:0] OPAD_BYTE = 8'h5d;
`else
    localparam [7:0] OPAD_BYTE = 8'h5c;
`endif
    localparam [7:0] IPAD_BYTE = 8'h36;

    localparam [3:0] S_IDLE = 4'd0,   // waiting for start
                     S_LK   = 4'd1,   // key stream into the core and k0
                     S_LKA  = 4'd2,   // short stream key: reset the core
                     S_WLK  = 4'd3,   // long stream key: wait for SHA-256(key)
                     S_IPAD = 4'd4,   // feed K0 ^ ipad
                     S_MSG  = 4'd5,   // message stream
                     S_WIN  = 4'd6,   // wait for the inner digest
                     S_OPAD = 4'd7,   // feed K0 ^ opad
                     S_OUTM = 4'd8,   // feed the inner digest
                     S_WOUT = 4'd9;   // wait for the outer digest

    reg [3:0]   state;
    reg         mac_v;
    reg [5:0]   cnt;            // byte index within an ipad/opad block or digest
    reg [6:0]   lkcnt;          // key stream bytes accepted, saturating at 65
    reg [511:0] k0;             // K0, byte 0 at [511:504]
    reg [255:0] inner;          // inner digest, byte 0 at [255:248]

    // ---------------------------------------------------------------
    // Hash core and its input mux
    // ---------------------------------------------------------------
    wire         c_ready;
    wire [255:0] c_digest;
    wire         c_dvalid;

    wire s_pad  = (state == S_IPAD) || (state == S_OPAD);
    wire s_outm = (state == S_OUTM);

    wire        c_valid = (state == S_LK)  ? lk_valid
                        : (state == S_MSG) ? in_valid
                        : (s_pad || s_outm);
    wire [7:0]  c_data  = (state == S_LK)  ? lk_data
                        : (state == S_MSG) ? in_data
                        : s_outm ? inner[255:248]
                        : (k0[511:504] ^ ((state == S_IPAD) ? IPAD_BYTE : OPAD_BYTE));
    wire        c_last  = (state == S_LK)  ? lk_last
                        : (state == S_MSG) ? in_last
                        : (s_outm && cnt == 6'd31);
    wire        c_empty = (state == S_LK)  ? lk_empty
                        : (state == S_MSG) ? in_empty
                        : 1'b0;

    wire accept = c_valid && c_ready;

    assign lk_ready  = (state == S_LK)  && c_ready;
    assign in_ready  = (state == S_MSG) && c_ready;

    // clear and S_LKA return the hash core to its reset state for one cycle.
    wire core_rst_n = rst_n && !clear && (state != S_LKA);

    sha256_core core (
        .clk(clk), .rst_n(core_rst_n),
        .in_valid(c_valid), .in_ready(c_ready), .in_data(c_data),
        .in_last(c_last), .in_empty(c_empty),
        .digest(c_digest), .digest_valid(c_dvalid)
    );

    assign mac       = mac_v ? c_digest : 256'd0;
    assign mac_valid = mac_v;
    assign busy      = (state != S_IDLE);

    // ---------------------------------------------------------------
    // Key handling
    // ---------------------------------------------------------------
    // Slot key: bytes at or beyond key_len are zero.
    function [255:0] mask_key;
        input [255:0] k;
        input [5:0]   n;
        integer i;
        begin
            for (i = 0; i < 32; i = i + 1)
                mask_key[255 - 8*i -: 8] = (i < n) ? k[255 - 8*i -: 8] : 8'h00;
        end
    endfunction

    // Stream key byte lkcnt is written into k0 (bytes beyond 64 are dropped;
    // k0 is replaced by the hash then).
    function [511:0] put_byte;
        input [511:0] cur;
        input [6:0]   idx;
        input [7:0]   data;
        integer i;
        begin
            for (i = 0; i < 64; i = i + 1)
                put_byte[511 - 8*i -: 8] = (i == idx) ? data : cur[511 - 8*i -: 8];
        end
    endfunction

    wire        lk_has_data = ~(lk_last && lk_empty);
    wire [6:0]  lk_total    = (lkcnt == 7'd65) ? 7'd65 : lkcnt + {6'd0, lk_has_data};
    wire [6:0]  lk_total_s  = (lk_total > 7'd65) ? 7'd65 : lk_total;

    always @(posedge clk) begin
        if (!rst_n || clear) begin
            state <= S_IDLE;
            mac_v <= 1'b0;
            cnt   <= 6'd0;
            lkcnt <= 7'd0;
            k0    <= 512'd0;
            inner <= 256'd0;
        end else begin
            case (state)
                S_IDLE: if (start) begin
                    mac_v <= 1'b0;
                    cnt   <= 6'd0;
                    lkcnt <= 7'd0;
                    if (key_long) begin
                        k0    <= 512'd0;
                        state <= S_LK;
                    end else begin
                        k0    <= {mask_key(key, (key_len > 6'd32) ? 6'd32 : key_len), 256'd0};
                        state <= S_IPAD;
                    end
                end

                S_LK: if (accept) begin
                    if (lk_has_data && lkcnt < 7'd64)
                        k0 <= put_byte(k0, lkcnt, lk_data);
                    lkcnt <= lk_total_s;
                    if (lk_last)
                        state <= (lk_total_s <= 7'd64) ? S_LKA : S_WLK;
                end

                S_LKA: state <= S_IPAD;     // core reset this cycle; k0 is the key

                S_WLK: if (c_dvalid) begin
                    k0    <= {c_digest, 256'd0};
                    state <= S_IPAD;
                end

                S_IPAD, S_OPAD: if (accept) begin
                    k0  <= {k0[503:0], k0[511:504]};    // 64 rotations restore k0
                    cnt <= cnt + 6'd1;
                    if (cnt == 6'd63)
                        state <= (state == S_IPAD) ? S_MSG : S_OUTM;
                end

                S_MSG: if (accept && in_last)
                    state <= S_WIN;

                S_WIN: if (c_dvalid) begin
                    inner <= c_digest;
                    cnt   <= 6'd0;
                    state <= S_OPAD;
                end

                S_OUTM: if (accept) begin
                    inner <= {inner[247:0], 8'h00};
                    cnt   <= cnt + 6'd1;
                    if (cnt == 6'd31)
                        state <= S_WOUT;
                end

                S_WOUT: if (c_dvalid) begin
                    mac_v <= 1'b1;
                    k0    <= 512'd0;
                    inner <= 256'd0;
                    state <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
