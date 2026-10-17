// Compile-time defines for simulating against the sky130_fd_sc_hd Verilog
// cell models. This file carries no design content -- it exists only
// because `klt functional-verification`'s request schema
// (`klt.functional_verification.request/1`) has no field for simulator
// build arguments / `+define+` macros (filed upstream; see
// `verification/gate-level/README.md`). Icarus compiles all
// `request.sources` into a single compilation unit in the order given, so
// listing this file *first* makes both macros visible to every later
// source, which is exactly what a `+define+` would have done.
//
// `FUNCTIONAL` selects each cell's *functional* (behavioural) model instead
// of its `specify`-block timing model. This is not a preference -- it is
// required for Icarus:
//
//     $ iverilog ... primitives.v sky130_fd_sc_hd.v modexp_post_route.v
//     warning: Timing checks are not supported and delayed signal
//              "D_delayed" will not be driven.
//
// Icarus does not implement the delayed-signal outputs of `$setuphold` /
// `$recrem`, so in the timing model every flop's `D_delayed`/`CLK_delayed`
// stays permanently `x` and the whole design simulates as `x`. Under
// `FUNCTIONAL` the same cells are plain UDP/primitive models and compile
// with zero warnings.
`define FUNCTIONAL

// `UNIT_DELAY` is the delay the sky130 functional models apply to their
// sequential UDP primitives (`sky130_fd_sc_hd__udp_dff$PR `UNIT_DELAY
// dff0 (...)`); combinational cells are unaffected. The cell models are
// `timescale 1ns / 1ps`, so `#1` is 1 ns -- one tenth of this design's
// 10 ns clock period. Giving flop outputs a nonzero delay is the standard
// way to keep a zero-delay gate-level netlist free of D/Q races at the
// clock edge; it is *not* a timing model of the routed design (see
// `verification/gate-level/README.md`, "What this does and does not
// model").
`define UNIT_DELAY #1
