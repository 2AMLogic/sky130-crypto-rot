// trng_if -- this block's side of the interface to sky130-trng
// (spec/trng-interface.md, decision records 0002 and 0006).
//
// Contents: the clock-domain crossing from the 50 kHz TRNG sample clock
// (observed as a signal, never used as a clock), coherent sampling of the
// sibling's stream and status pins at t_fall, the seed collector with the
// gating rules of section 3.4, a write-only sequencer for the sibling's
// register bus (section 3.2), and the alarm -> zeroize path.
//
// Makes no entropy claim and no security claim beyond the properties in
// spec/key-isolation-properties.md that the benches and formal files check.
// The sibling's RTL is not copied here (reuse.lock.json pins it).
//
// Reset: rst_n is asynchronous-assert, synchronous-release. While reset is
// asserted `zeroize` is high. `zeroize` also rises 2 cycles after a TRNG alarm
// reaches this domain, and for as long as `sw_zeroize` or the synchronized
// alarm is high. Everything key-bearing in this block clears on `zeroize`.
//
// Seed collector: seed_req (pulse) starts collecting INST_WORDS (seed_reseed
// = 0) or RESEED_WORDS (seed_reseed = 1) words into `seed`; word i lands in
// seed[32*i +: 32], in arrival order. seed_ready rises when complete and
// `seed` is then held until seed_release (pulse) clears the buffer. A request
// while collecting or ready is ignored. The sequence of events at t_fall is
// in the README of this directory.
//
// Bus: bus_re is tied to 0 and the sibling's bus_rdata is not an input of
// this module at all (property P-14). The only writes are
// CTRL = 3'b011 once after reset, ALARM = 3'b111 after zeroize completes, and
// CTRL = 3'b100 (SOFT_RST) followed by CTRL = 3'b011 to restart after an alarm.

module trng_if #(
    parameter INST_WORDS   = 16,
    parameter RESEED_WORDS = 8
) (
`ifdef FORMAL
    output wire         fv_zero,
    output wire         fv_alarm_s2,
`endif
    input  wire         clk,            // core clock
    input  wire         rst_n,          // async assert, sync release
    input  wire         sw_zeroize,     // software ZEROIZE (level)

    // sibling pins
    input  wire         trng_clk,       // 50 kHz sample clock, observed only
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

    // seed collector
    input  wire         seed_req,
    input  wire         seed_reseed,
    input  wire         seed_release,
    output wire         seed_ready,
    output wire [32*((INST_WORDS > RESEED_WORDS) ? INST_WORDS : RESEED_WORDS)-1:0] seed,

    output wire         zeroize,
    output wire         alarm_zeroized
);

    localparam SEEDW = 32 * ((INST_WORDS > RESEED_WORDS) ? INST_WORDS : RESEED_WORDS);
    localparam [3:0] A_CTRL = 4'h0, A_ALARM = 4'h4;
    localparam [2:0] SQ_HOLD = 3'd0, SQ_RUN = 3'd1, SQ_AWAIT = 3'd2, SQ_SRST = 3'd3,
                     SQ_EN = 3'd4, SQ_CLEARED = 3'd5;

    // -- reset: async assert, sync release ----------------------------------
    reg rs1, rs2;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin rs1 <= 1'b0; rs2 <= 1'b0; end
        else        begin rs1 <= 1'b1; rs2 <= rs1;  end

    // -- clock-domain crossing (trng-interface.md 3.1) ----------------------
    reg c1, c2, c3;
    always @(posedge clk) begin c1 <= trng_clk; c2 <= c1; c3 <= c2; end
    wire t_rise =  c2 & ~c3;
    wire t_fall = ~c2 &  c3;

    // alarm has its own 2-flop synchronizer feeding zeroize directly
    reg a1, a2;
    always @(posedge clk) begin a1 <= trng_alarm; a2 <= a1; end

    // zeroize: registered, asserted by reset, synchronized alarm or software
    reg zr_q, zr_d1;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin zr_q <= 1'b1; zr_d1 <= 1'b1; end
        else        begin zr_q <= ~rs2 | a2 | sw_zeroize; zr_d1 <= zr_q; end
    assign zeroize = zr_q;

    // sibling reset: async assert, released aligned to a sample-clock rising edge
    reg trst_q;
    always @(posedge clk or negedge rst_n)
        if (!rst_n)               trst_q <= 1'b0;
        else if (t_rise && rs2)   trst_q <= 1'b1;
    assign trng_rst_n = trst_q;

    // -- sampling at t_fall --------------------------------------------------
    wire bad_now = trng_gated | ~trng_startup_done | trng_alarm;
    reg  prev_bad_q;                 // gated/startup/alarm at the previous t_fall (1 after reset)
    reg  ordy_q;
    reg  collecting_q, ready_q, reseed_q;
    reg  [4:0] wcount_q;
    reg  [SEEDW-1:0] seed_q;

`ifdef TRNG_IF_NEG_COUNT
    wire [4:0] need = (reseed_q ? RESEED_WORDS : INST_WORDS) - 1;     // negative control: one word short
`else
    wire [4:0] need = reseed_q ? RESEED_WORDS : INST_WORDS;
`endif
`ifdef TRNG_IF_NEG_PREV
    wire       prev_ok = 1'b1;                                         // negative control: ignore the previous sample
`else
    wire       prev_ok = !prev_bad_q;
`endif
    wire       take = t_fall && collecting_q && trng_out_valid && !bad_now && prev_ok;

    // -- register-bus sequencer (writes only) --------------------------------
    reg [2:0]  sq_q;
    reg        we_q;
    reg [3:0]  addr_q;
    reg [31:0] wdata_q;
    assign trng_bus_re    = 1'b0;
    assign trng_bus_we    = we_q;
    assign trng_bus_addr  = addr_q;
    assign trng_bus_wdata = wdata_q;
    assign trng_out_ready = ordy_q;
    assign seed           = seed_q;
    assign seed_ready     = ready_q;
    assign alarm_zeroized = (sq_q != SQ_HOLD) && (sq_q != SQ_RUN);

    always @(posedge clk) begin
        if (zeroize) begin
            prev_bad_q   <= 1'b1;
            ordy_q       <= 1'b0;
            collecting_q <= 1'b0;
            ready_q      <= 1'b0;
            reseed_q     <= 1'b0;
            wcount_q     <= 5'd0;
            seed_q       <= {SEEDW{1'b0}};
        end else begin
            if (seed_release) begin
                ready_q  <= 1'b0;
                seed_q   <= {SEEDW{1'b0}};
                wcount_q <= 5'd0;
            end else if (seed_req && !collecting_q && !ready_q) begin
                collecting_q <= 1'b1;
                reseed_q     <= seed_reseed;
                wcount_q     <= 5'd0;
            end

            if (t_fall) begin
                prev_bad_q <= bad_now;
                ordy_q     <= take;
`ifdef TRNG_IF_NEG_DISCARD
                if (1'b0) begin                                       // negative control: never discard
`else
                if (collecting_q && bad_now) begin
`endif
                    // a seed is words from one ungated epoch: discard and restart at word 0
                    seed_q   <= {SEEDW{1'b0}};
                    wcount_q <= 5'd0;
                end
                if (take) begin
                    seed_q[32 * wcount_q +: 32] <= trng_out_data;
                    wcount_q <= wcount_q + 5'd1;
                    if (wcount_q + 5'd1 == need) begin
                        collecting_q <= 1'b0;
                        ready_q      <= 1'b1;
                    end
                end
            end
        end
    end

    // The sequencer is NOT cleared by zeroize (it must run while a held alarm
    // keeps zeroize asserted); only by reset. It holds no key material.
    always @(posedge clk) begin
        if (!rs2) begin
            sq_q <= SQ_HOLD;
            we_q <= 1'b0; addr_q <= 4'd0; wdata_q <= 32'd0;
        end else if (t_fall) begin
            we_q <= 1'b0;
            case (sq_q)
                SQ_HOLD: if (trst_q) begin
                    we_q <= 1'b1; addr_q <= A_CTRL; wdata_q <= 32'h3;
                    sq_q <= SQ_RUN;
                end
                SQ_RUN: if (trng_alarm) sq_q <= SQ_AWAIT;
                SQ_AWAIT: if (zr_q && zr_d1) begin
                    // zeroize has completed: only now clear the sibling's sticky alarm
                    we_q <= 1'b1; addr_q <= A_ALARM; wdata_q <= 32'h7;
                    sq_q <= SQ_SRST;
                end
                SQ_SRST: begin
                    we_q <= 1'b1; addr_q <= A_CTRL; wdata_q <= 32'h4;
                    sq_q <= SQ_EN;
                end
                SQ_EN: begin
                    we_q <= 1'b1; addr_q <= A_CTRL; wdata_q <= 32'h3;
                    sq_q <= SQ_CLEARED;
                end
                SQ_CLEARED: sq_q <= trng_alarm ? SQ_AWAIT : SQ_RUN;
                default: sq_q <= SQ_HOLD;
            endcase
        end
    end

`ifdef FORMAL
    assign fv_zero     = (seed_q == {SEEDW{1'b0}}) && !ready_q && !collecting_q && !ordy_q;
    assign fv_alarm_s2 = a2;
    // properties hold for states reachable from a reset: f_on is set once reset has been seen
    reg f_on = 1'b0;
    always @(posedge clk) if (!rs2) f_on <= 1'b1;
    // a word is never accepted unless the previous and current samples were clean
    always @* if (f_on && take) assert (!prev_bad_q && !bad_now);
    // the sequencer only writes the three allowed registers/values, and never reads
    always @* if (f_on && we_q) assert ((addr_q == A_CTRL && (wdata_q == 32'h3 || wdata_q == 32'h4)) ||
                                        (addr_q == A_ALARM && wdata_q == 32'h7));
    always @* assert (!trng_bus_re);
`endif

endmodule
