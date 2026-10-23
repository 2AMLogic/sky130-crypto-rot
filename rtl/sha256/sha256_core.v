// sha256_core -- SHA-256 (FIPS 180-4), byte-serial in, one round per cycle.
//
// Scope: the hash core only. No HMAC, no bus interface, no key material, no
// secret handling. Byte-oriented messages (length a whole number of bytes).
//
// Input stream (accepted on a rising clk edge when in_valid && in_ready):
//   in_data[7:0]  next message byte, in order.
//   in_last       this transfer ends the message.
//   in_empty      with in_last: the transfer carries NO data byte (in_data is
//                 ignored). This is how a zero-length message, or a message
//                 whose last data byte was already sent without in_last, is
//                 ended. Ignored when in_last is low.
// The core pads (0x80, zeros, 64-bit big-endian bit length) itself in the
// cycle the last transfer is accepted; no padding is clocked in serially.
//
// Output: digest[255:0] is H0..H7, H0 in the most significant word, valid
// while digest_valid is high. digest_valid falls on the next accepted
// transfer and rises when the digest of the message is complete. The digest
// is overwritten when the next message's first block is committed (its 64th
// byte, or its last transfer), so the consumer must take it before then.
//
// Latency: one block takes 65 cycles. The cycle on which the transfer that
// completes a block is accepted is edge 0 ("block load"); the 64 rounds are
// edges 1..64; edge 65 adds the working variables into H. A message whose
// padding spills into a second block (pad position >= 56 in its last block)
// hashes that block back to back, so digest_valid rises at edge 130.
// in_ready is low while a block is being hashed (the block buffer doubles as
// the message-schedule window), so a stream stalls 65 cycles per 64 bytes.
//
// Message length is counted in a 61-bit byte counter (2^64 bits, the FIPS
// 180-4 limit); a longer message wraps the length field.
//
// Synchronous active-low reset on control state only. The data path
// (block buffer, working variables, H) is not reset; it is fully written
// before it is read.

module sha256_core (
    input  wire         clk,
    input  wire         rst_n,

    input  wire         in_valid,
    output wire         in_ready,
    input  wire [7:0]   in_data,
    input  wire         in_last,
    input  wire         in_empty,

    output wire [255:0] digest,
    output wire         digest_valid
);

    localparam [1:0] S_COLLECT = 2'd0, S_ROUND = 2'd1, S_ADD = 2'd2;

    localparam [255:0] H_INIT = {
        32'h6a09e667, 32'hbb67ae85, 32'h3c6ef372, 32'ha54ff53a,
        32'h510e527f, 32'h9b05688c, 32'h1f83d9ab, 32'h5be0cd19
    };

    reg [1:0]   state;
    reg         fresh;          // next block committed is the first of a message
    reg         final_blk;      // block being hashed is the last of the message
    reg         spill;          // a length-only block follows the block being hashed
    reg         pad80;          // that block must carry the 0x80 marker (p == 64)
    reg         dvalid;
    reg [60:0]  len;            // message bytes accepted so far (low 6 = block position)
    reg [5:0]   t;              // round index
    reg [511:0] w;              // block buffer / schedule window; byte 0 at [511:504]
    reg [255:0] hh;             // chaining value H0..H7
    reg [31:0]  a, b, c, d, e, f, g, h;

    assign in_ready     = (state == S_COLLECT);
    assign digest       = hh;
    assign digest_valid = dvalid;

    wire accept = in_valid && in_ready;

    // ---------------------------------------------------------------
    // Block-buffer write: one function covers a plain byte write, the
    // final (padding) write and the length-only block. For a byte index i:
    //   i <  n               keep
    //   i == n, has_data     the data byte
    //   i == p               0x80
    //   otherwise            0
    // and, with do_len, bytes 56..63 take the big-endian bit length.
    // Zeroing above n on a plain write is harmless: those bytes are not
    // written yet and the block is not hashed until it is complete.
    // ---------------------------------------------------------------
    function [511:0] fill;
        input [511:0] cur;
        input [6:0]   n;
        input         has_data;
        input [7:0]   data;
        input [6:0]   p;
        input         do_len;
        input [63:0]  lenbits;
        integer i;
        reg [7:0] bt;
        begin
            for (i = 0; i < 64; i = i + 1) begin
                if (i < n)
                    bt = cur[511 - 8*i -: 8];
                else if (has_data && i == n)
                    bt = data;
                else if (i == p)
                    bt = 8'h80;
                else
                    bt = 8'h00;
                if (do_len && i >= 56)
                    bt = lenbits[63 - 8*(i-56) -: 8];
                fill[511 - 8*i -: 8] = bt;
            end
        end
    endfunction

    wire        pad2      = (state == S_ADD) && spill;
    wire        has_data  = pad2 ? 1'b0 : ~(in_last && in_empty);
    wire [6:0]  n_eff     = pad2 ? 7'd0 : {1'b0, len[5:0]};
    wire [6:0]  p_last    = n_eff + {6'd0, has_data};          // 0x80 position, 0..64
    wire [6:0]  p_eff     = pad2 ? (pad80 ? 7'd0 : 7'd64)
                          : (in_last ? p_last : 7'd64);
    wire        fits      = (p_last <= 7'd55);                 // length fits this block
    wire        do_len    = pad2 ? 1'b1 : (in_last && fits);
    wire [60:0] len_inc   = len + 61'd1;
    wire [60:0] len_after = (has_data && !pad2) ? len_inc : len;
    wire [511:0] w_fill   = fill(w, n_eff, has_data, in_data, p_eff, do_len,
                                 {len_after, 3'b000});

    wire commit = accept && (in_last || len[5:0] == 6'd63);

    // ---------------------------------------------------------------
    // Round and schedule
    // ---------------------------------------------------------------
    function [31:0] rotr;
        input [31:0] x;
        input integer n;
        rotr = (x >> n) | (x << (32 - n));
    endfunction

    function [31:0] kconst;
        input [5:0] i;
        case (i)
            6'd0:  kconst = 32'h428a2f98; 6'd1:  kconst = 32'h71374491;
            6'd2:  kconst = 32'hb5c0fbcf; 6'd3:  kconst = 32'he9b5dba5;
            6'd4:  kconst = 32'h3956c25b; 6'd5:  kconst = 32'h59f111f1;
            6'd6:  kconst = 32'h923f82a4; 6'd7:  kconst = 32'hab1c5ed5;
            6'd8:  kconst = 32'hd807aa98; 6'd9:  kconst = 32'h12835b01;
            6'd10: kconst = 32'h243185be; 6'd11: kconst = 32'h550c7dc3;
            6'd12: kconst = 32'h72be5d74; 6'd13: kconst = 32'h80deb1fe;
            6'd14: kconst = 32'h9bdc06a7; 6'd15: kconst = 32'hc19bf174;
            6'd16: kconst = 32'he49b69c1;
`ifdef SHA256_NEG_CTRL
            // Negative control: one K constant off by one bit.
            6'd17: kconst = 32'hefbe4787;
`else
            6'd17: kconst = 32'hefbe4786;
`endif
            6'd18: kconst = 32'h0fc19dc6; 6'd19: kconst = 32'h240ca1cc;
            6'd20: kconst = 32'h2de92c6f; 6'd21: kconst = 32'h4a7484aa;
            6'd22: kconst = 32'h5cb0a9dc; 6'd23: kconst = 32'h76f988da;
            6'd24: kconst = 32'h983e5152; 6'd25: kconst = 32'ha831c66d;
            6'd26: kconst = 32'hb00327c8; 6'd27: kconst = 32'hbf597fc7;
            6'd28: kconst = 32'hc6e00bf3; 6'd29: kconst = 32'hd5a79147;
            6'd30: kconst = 32'h06ca6351; 6'd31: kconst = 32'h14292967;
            6'd32: kconst = 32'h27b70a85; 6'd33: kconst = 32'h2e1b2138;
            6'd34: kconst = 32'h4d2c6dfc; 6'd35: kconst = 32'h53380d13;
            6'd36: kconst = 32'h650a7354; 6'd37: kconst = 32'h766a0abb;
            6'd38: kconst = 32'h81c2c92e; 6'd39: kconst = 32'h92722c85;
            6'd40: kconst = 32'ha2bfe8a1; 6'd41: kconst = 32'ha81a664b;
            6'd42: kconst = 32'hc24b8b70; 6'd43: kconst = 32'hc76c51a3;
            6'd44: kconst = 32'hd192e819; 6'd45: kconst = 32'hd6990624;
            6'd46: kconst = 32'hf40e3585; 6'd47: kconst = 32'h106aa070;
            6'd48: kconst = 32'h19a4c116; 6'd49: kconst = 32'h1e376c08;
            6'd50: kconst = 32'h2748774c; 6'd51: kconst = 32'h34b0bcb5;
            6'd52: kconst = 32'h391c0cb3; 6'd53: kconst = 32'h4ed8aa4a;
            6'd54: kconst = 32'h5b9cca4f; 6'd55: kconst = 32'h682e6ff3;
            6'd56: kconst = 32'h748f82ee; 6'd57: kconst = 32'h78a5636f;
            6'd58: kconst = 32'h84c87814; 6'd59: kconst = 32'h8cc70208;
            6'd60: kconst = 32'h90befffa; 6'd61: kconst = 32'ha4506ceb;
            6'd62: kconst = 32'hbef9a3f7; 6'd63: kconst = 32'hc67178f2;
        endcase
    endfunction

    // Window: w0 = W[t], w1 = W[t+1], w9 = W[t+9], w14 = W[t+14] (W[t+16] is
    // the word shifted in, valid for every t).
    wire [31:0] w0  = w[511:480];
    wire [31:0] w1  = w[479:448];
    wire [31:0] w9  = w[223:192];
    wire [31:0] w14 = w[63:32];
    wire [31:0] sg0 = rotr(w1, 7)   ^ rotr(w1, 18)  ^ (w1  >> 3);
    wire [31:0] sg1 = rotr(w14, 17) ^ rotr(w14, 19) ^ (w14 >> 10);
    wire [31:0] w_new = sg1 + w9 + sg0 + w0;

    wire [31:0] bs1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
    wire [31:0] bs0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
    wire [31:0] ch  = (e & f) ^ (~e & g);
    wire [31:0] maj = (a & b) ^ (a & c) ^ (b & c);
    wire [31:0] t1  = h + bs1 + ch + kconst(t) + w0;
    wire [31:0] t2  = bs0 + maj;

    wire [255:0] sum = {
        hh[255:224] + a, hh[223:192] + b, hh[191:160] + c, hh[159:128] + d,
        hh[127:96]  + e, hh[95:64]   + f, hh[63:32]    + g, hh[31:0]    + h
    };

    always @(posedge clk) begin
        if (!rst_n) begin
            state  <= S_COLLECT;
            fresh  <= 1'b1;
            final_blk <= 1'b0;
            spill  <= 1'b0;
            pad80  <= 1'b0;
            dvalid <= 1'b0;
            len    <= 61'd0;
            t      <= 6'd0;
        end else begin
            case (state)
                S_COLLECT: if (accept) begin
                    dvalid <= 1'b0;
                    w      <= w_fill;
                    len    <= len_after;
                    if (commit) begin
                        if (fresh) begin
                            hh <= H_INIT;
                            {a, b, c, d, e, f, g, h} <= H_INIT;
                            fresh <= 1'b0;
                        end
                        final_blk <= in_last && fits;
                        spill     <= in_last && !fits;
                        pad80     <= (p_last == 7'd64);
                        t         <= 6'd0;
                        state     <= S_ROUND;
                    end
                end

                S_ROUND: begin
                    w <= {w[479:0], w_new};
                    {a, b, c, d, e, f, g, h} <= {t1 + t2, a, b, c, d + t1, e, f, g};
                    t <= t + 6'd1;
                    if (t == 6'd63)
                        state <= S_ADD;
                end

                S_ADD: begin
                    hh <= sum;
                    {a, b, c, d, e, f, g, h} <= sum;
                    if (final_blk) begin
                        dvalid <= 1'b1;
                        fresh  <= 1'b1;
                        len    <= 61'd0;
                        state  <= S_COLLECT;
                    end else if (spill) begin
                        // Second block: load the length-only block and go on.
                        w         <= w_fill;
                        spill     <= 1'b0;
                        final_blk <= 1'b1;
                        t         <= 6'd0;
                        state     <= S_ROUND;
                    end else begin
                        state <= S_COLLECT;
                    end
                end

                default: state <= S_COLLECT;
            endcase
        end
    end

endmodule
