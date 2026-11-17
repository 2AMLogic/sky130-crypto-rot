#!/usr/bin/env python3
"""Write the append-only record for verification/formal/run.sh.

Reads flow/build/formal/results.tsv (one line per sby task). Refuses to record
unless every task met its expectation -- with the netlist exception of a proof
that stopped at its depth or the 1500 s per-task cap: it is recorded as
"reached depth N, not proven" (issue #177). A run whose work directory has no
config.sby at all, a config.sby with no `mode` line in its `[options]` block,
or a bounded (`mode bmc`/`cover`) task whose config.sby names no depth, also
refuses: the mode or the Depth column cannot be filled (issue #224, #243).
A depth-less `mode prove` task is the unbounded proof and records as
`unbounded`. With --check-only it stops right after that verdict and writes
nothing, so run.sh judges every run through this one EXPECT table, --record or
not (issue #207). Standard library only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "flow/common"))
import record_lib as rc  # noqa: E402
from record_lib import sby_depth, sby_mode  # noqa: E402

EXPERIMENT = "drbg-trng-formal"
# The inputs OUTSIDE this directory. The tracked files beside this generator
# are derived by record_lib.own_inputs(), and the shared flow helpers by
# shared_inputs(); neither is listed here (issues #124, #146).
INPUTS = (
    "rtl/drbg/ctr_drbg.v",
    "rtl/trng_if/trng_if.v",
    "spec/key-isolation-properties.md",
)

# (file, task) -> (expectation, meaning). Expectations: PASS (proof/bounded check),
# FAIL (negative control / vacuity), and for netlist proofs PASS_OR_DEPTH (a
# run that stops at its depth or the time cap is recorded at that depth, not
# reported as proven).
EXPECT = {
    ("p7_p8.sby", "prove"): ("PASS", "P-7 and P-8 hold in every reachable state, unbounded (abc pdr), shipped interval 65536; the 17-bit counter is bounded by induction (`ctr_q <= interval + 1`), not by running 2^16 steps"),
    ("p7_p8.sby", "reach_valid"): ("FAIL", "vacuity: `blk_valid` is reachable (counterexample to `assert(!blk_valid)`)"),
    ("p7_p8.sby", "reach_over"): ("FAIL", "vacuity: `reseed_required` is reachable (interval 1)"),
    ("p7_p8.sby", "neg_interval"): ("FAIL", "RTL defect: one request too many allowed before RESEED_REQUIRED is caught by the P-8 assertions (interval 1)"),
    ("p7_p8.sby", "neg_seeded"): ("FAIL", "RTL defect: generate before instantiate is caught by the P-7 assertion"),
    ("p9.sby", "bmc"): ("PASS", "P-9 bounded check, depth 30 from reset"),
    ("p9.sby", "prove"): ("PASS", "P-9 unbounded (abc pdr)"),
    ("p9.sby", "neg_bound"): ("FAIL", "the same claim one cycle earlier fails: the 2-cycle response bound is tight, not slack"),
    ("p9.sby", "reach_nonzero"): ("FAIL", "vacuity: the registers can be non-zero before the alarm"),
    ("p9.sby", "neg_zeroize"): ("FAIL", "RTL defect: DRBG V surviving zeroize is caught"),
    ("net_p7_p8.sby", "net_prove"): ("PASS_OR_DEPTH", "P-7 and P-8 on the netlist, unbounded (abc pdr, the RTL proofs' own engine), shipped interval 65536; the netlist binding (literals, op_q over its driven bits) is machine-checked inside the run"),
    ("net_p7_p8.sby", "net_reach_valid"): ("FAIL", "vacuity on the netlist: `blk_valid` is reachable"),
    ("net_p7_p8.sby", "net_reach_over"): ("FAIL", "vacuity on the netlist: `reseed_required` is reachable (interval-1 netlist)"),
    ("net_p7_p8.sby", "net_neg_interval"): ("FAIL", "netlist synthesized from the DRBG_NEG_INTERVAL mutant: one request too many is caught by the P-8 assertions (interval 1); a separate klt synthesize run of the mutated RTL"),
    ("net_p7_p8.sby", "net_neg_seeded"): ("FAIL", "netlist synthesized from the DRBG_NEG_SEEDED mutant: generate before instantiate is caught by the P-7 assertion; a separate klt synthesize run of the mutated RTL"),
    ("net_p9.sby", "net_bmc"): ("PASS", "P-9 bounded on the netlists, depth 30 from reset"),
    ("net_p9.sby", "net_prove"): ("PASS_OR_DEPTH", "P-9 unbounded on the netlists (abc pdr)"),
    ("net_p9.sby", "net_neg_bound"): ("FAIL", "the same claim one cycle earlier fails on the netlist: the 2-cycle response bound is tight, not slack"),
    ("net_p9.sby", "net_reach_nonzero"): ("FAIL", "vacuity on the netlists: the registers can be non-zero before the alarm"),
    ("net_p9.sby", "net_neg_zeroize"): ("FAIL", "netlist synthesized from the DRBG_NEG_ZEROIZE mutant: DRBG V surviving zeroize is caught; a separate klt synthesize run of the mutated RTL"),
}


def steps_checked(d: Path) -> int | None:
    """The last step the engine checked, from the run's logfile.txt.

    The scrape itself is record_lib's shared sby_steps_checked(), so this and
    the keyladder generator cannot state different reached depths (issue #259).
    """
    log = d / "logfile.txt"
    return rc.sby_steps_checked(log.read_text()) if log.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()
    rows = [line.split("\t") for line in (args.out_dir / "results.tsv").read_text().splitlines() if line]
    if not rows:
        print("formal: not recording, no task results found", file=sys.stderr)
        return 1
    verdicts = []
    depth_reached = []
    for r in rows:
        f, t, status, rc_s, frame = r[0], r[1], r[2], r[3], r[5]
        key = (f, t)
        if key not in EXPECT:
            print(f"formal: not recording, unexpected task row {f} {t}", file=sys.stderr)
            return 1
        expect = EXPECT[key][0]
        d = args.out_dir / f"{f[:-4]}_{t}"
        depth = sby_depth(d)
        mode = sby_mode(d)
        if expect == "PASS":
            ok = rc_s == "0" and status == "PASS"
        elif expect == "FAIL":
            ok = rc_s == "0" and status == "FAIL"
        else:  # PASS_OR_DEPTH: a netlist proof must PASS, or stop inconclusively
            # (recorded as not proven, with the depth only when the engine reported one)
            ok = (rc_s == "0" and status == "PASS") or status in ("TIMEOUT", "UNKNOWN")
            if ok and status != "PASS":
                steps = steps_checked(d)
                depth_reached.append((f, t, steps, status))
        if not ok:
            verdicts.append(f"{f} {t}: expected {expect}, got status {status} (sby exit {rc_s})")
        if mode is None:
            # A task needs a mode statement whatever its status: the record is
            # append-only, and what ran cannot be stated without one (issue
            # #224). sby_mode's None has two meanings -- say which occurred,
            # not a blanket "no config.sby" (issue #243).
            if not (d / "config.sby").exists():
                verdicts.append(f"{f} {t}: the run's work directory has no config.sby: "
                                "neither the mode nor the depth of what ran can be stated")
            else:
                verdicts.append(f"{f} {t}: the run's config.sby has no mode line in [options]: "
                                "the mode of what ran cannot be stated")
        elif mode in ("bmc", "cover") and depth is None:
            verdicts.append(f"{f} {t}: mode {mode} is bounded, but the run's config.sby "
                            "names no depth: the Depth column cannot be filled")
        # A depth-less `mode prove` run needs neither guard: it is the unbounded
        # proof (p7_p8.sby/prove, p9.sby/prove) and records as `unbounded`.
    if verdicts:
        print("formal: not recording, a task did not meet its expectation:", file=sys.stderr)
        for v in verdicts:
            print(f"  {v}", file=sys.stderr)
        return 1
    if args.check_only:
        # Judged and clean; stop before require_clean_inputs / the tool-version
        # and record work, so a check costs nothing but reading results.tsv
        # (the keyladder generator's contract, issue #207).
        return 0
    rev = rc.require_clean_inputs(INPUTS, generator=__file__)
    v = rc.tool_versions()
    v["sby"] = rc.run(str(rc.REPO / ".venv/bin/yowasp-sby"), "--version")

    def depth_of(f, t):
        # Reachable only after the verdict guards: a None depth here is a
        # depth-less `mode prove` run -- the unbounded proof -- not a broken one.
        depth = sby_depth(args.out_dir / f"{f[:-4]}_{t}")
        return "unbounded" if depth is None else depth

    def result_cell(f, t, s):
        if s in ("TIMEOUT", "UNKNOWN") and (f, t) in EXPECT and EXPECT[(f, t)][0] == "PASS_OR_DEPTH":
            steps = steps_checked(args.out_dir / f"{f[:-4]}_{t}")
            return (f"{s} -- reached depth {steps}, not proven" if steps
                    else f"{s} -- not proven, no depth reached")
        return s

    table = "\n".join(
        f"  | `{f}` | `{t}` | {result_cell(f, t, s)} | {e} | {depth_of(f, t)} | {fr} | {sec} | "
        f"{EXPECT[(f, t)][1]} |"
        for f, t, s, _rc, e, fr, sec in rows)
    depth_note = ""
    if depth_reached:
        depth_note = (" Rows recorded as not-proven did NOT close: they state the last "
                      "step the engine checked (or that it reached no depth) and are not "
                      "proof claims.")
    body = f"""- **Claim**: properties P-7, P-8 and P-9 of `spec/key-isolation-properties.md` hold on the RTL of `rtl/drbg/ctr_drbg.v` and `rtl/trng_if/trng_if.v` and on the `klt synthesize` sky130_fd_sc_hd netlist of the same modules as written in the task table below, with the AES engine abstracted to its busy/done handshake (an unconstrained latency of at least one cycle and an unconstrained result: the DRBG's control decisions never read the AES result). P-7: `blk_valid` implies seeded and not reseed-required. P-8: the reseed counter never exceeds interval + 1, a generate is never started above the interval, and the exhausted state persists until a reseed completes. P-9: if the synchronized alarm was high two cycles ago, DRBG `Key`/`V`, `chain`, df/Update working registers, the output register, the seed buffer and `out_ready` are zero (so zero within two core cycles of the synchronizer output, within the stated bound of 4, and held zero while the alarm stays asserted).{depth_note} Not covering key slots (issue #46, top-level #88), the AES core's own registers (issue #43), or the clock-domain timing of the synchronizer (modelled as an ordinary register chain at the core clock). This record supersedes 20261031-003845-70b0a85, which covered the RTL half only (its pointer named issue #46); the netlist re-proof tracked as issue #177.
- **Design provenance**: RTL and the `klt synthesize` sky130_fd_sc_hd netlist (liberty corner `tt_025C_1v80`, pre-P&R), formal. Both halves run Yosys-internal engines through SymbiYosys (`abc pdr`/`abc bmc3`); the netlist cells are modelled by Yosys from the liberty `function`/`ff` groups (`read_liberty -ignore_miss_func`), no hand-written cell models.
- **Run configuration**: `./scripts/setup-env.sh` then `./verification/formal/run.sh --record` (RTL) and `./verification/formal/run.sh --netlist --record` (netlist). Engines `abc pdr` (unbounded) and `abc bmc3` (bounded) on both the RTL and the netlist tasks, `aigsmt none`. Assertions are in the RTL under `ifdef FORMAL`; wrappers `fv_drbg.v` and `fv_p9.v` supply the environment (free commands, sizes, seeds, sibling pins and zeroize; reset/zeroize asserted in the first cycle, assertions gated on a first-zeroize/reset flag because the design has no reset of its own).
- **Result**: every task below met its expectation. The Depth column is the depth SymbiYosys ran each task at, read from the `config.sby` in that run's own work directory (the issue #165 reader contract); a bounded task must name one and the run refuses to record without it, while an unbounded `mode prove` task names none by design and is recorded as `unbounded`.

  | file | task | sby result | engine | depth | counterexample frame | seconds | meaning |
  |---|---|---|---|---|---|---|---|
{table}

  Tasks named `reach_*` and `neg_*` (RTL and netlist) are expected to FAIL (sby `expect fail`); their failure is the evidence that the passing tasks are not vacuous and that the checks can see a defect, on the RTL and on the mapped netlist alike.
- **Netlist binding**: the property text is lifted from the RTL's `ifdef FORMAL` blocks at run time and spliced, unchanged except for the literal binding, into generated COPIES of the netlist modules by `gen_netlist.py` (pure-insertion checked); `rtl/` is not modified. The spliced text replaces the RTL localparam/parameter names with numeric literals derived by parsing the RTL (`S_IDLE`, `S_GEN_ISSUE`, `S_UPD_WAIT`, `RESEED_INTERVAL`, and `SEEDW` for trng_if), so a later RTL re-encoding fails the parse loudly instead of binding to nothing. `synth`'s `fsm` pass re-encoded `op_q` (2 -> 3 bits, one flop optimized away), so OP_GEN is not a literal: per variant netlist, a directed icarus probe (`tb_net_probe.v`, over the netlist flattened with the pinned yosys) reads `op_q` after an accepted instantiate and an accepted generate, and OP_GEN is bound as a conjunction over the bits synthesis kept (an optimized-away bit is an unconstrained net in the formal run and must stay out of the binding). The registers the properties name survive synthesis as named wires (checked by name and width per module by `gen_netlist.py`: key_q, v_q, chain_q, tk_q, tx_q, t0_q, prov_q, bd_q, bv_q, bl_q, seeded_q, state_q, ctr_q, op_q, ocnt_q; trng_if: seed_q, ready_q, collecting_q, ordy_q, a2), and each netlist proof machine-checks its own binding (`busy == (state_q != S_IDLE)` and `state_q == S_GEN_ISSUE |-> <op_q == OP_GEN>`, generated checks beyond the RTL text). `fv_zero`/`fv_alarm_s2` are rebuilt as ports of the netlist modules from the surviving register wires (synthesis runs without FORMAL, so the netlist has no fv_* port); `fv_drbg.v`/`fv_p9.v` are used as wrappers unchanged except the instantiation parameter lists a netlist module does not carry (each removal a checked single edit) -- the assertion text binds unchanged.
- **Netlist negative controls**: separate `klt synthesize` runs of the mutant RTL, preprocessed with the existing `ifdef` defines (`DRBG_NEG_SEEDED`, `DRBG_NEG_ZEROIZE`, `DRBG_NEG_INTERVAL`); the interval-1 runs (`net_reach_over`, `net_neg_interval`) are source-mutated copies with `RESEED_INTERVAL = 1`, because `klt synthesize` cannot set preprocessor defines or submodule parameter overrides (filed upstream as 2AMLogic/klayout-tools#4196 and #4698). A netlist control that does not fail with a counterexample fails the run.
- **Tool gap**: the sby in the pinned venv (`yowasp-sby`) ships no SMT solver, so `smtbmc` engines, counterexample waveforms (`aigsmt`) and cover traces are unavailable, and it looks for `yosys-witness`/`yosys-smtbmc` by names the venv does not provide (shimmed under `flow/build/formal-bin/`). Filed on `2AMLogic/klayout-tools` as a generic tool gap. The netlist tasks use the same Yosys-internal engines (`abc pdr`/`abc bmc3`), so they need no SMT solver either. Synthesis additionally runs with a short `TMPDIR`: yosys's abc pass deadlocks when the temp path is long (yosys-abc's readline wraps the echoed `source` line and the reuse protocol never completes) -- 2AMLogic/klayout-tools#5780; `run.sh` pins one for the synthesis step.
- **Tool versions**: {v['sby']}, yowasp-yosys {v['yowasp_yosys']} (`yosys.wasm` {v['yosys_wasm']}), Python {v['python']}, klt pinned at `{v['klt_pin']}`.
- **Links**: `verification/formal/`, `spec/key-isolation-properties.md`, `rtl/drbg/`, `rtl/trng_if/`, `verification/records/keyladder-formal/` (the netlist-flow precedent), 2AMLogic/klayout-tools#4196, #4698, #5780, #5804 (the pinned wheel's `sat` traps on a flattened liberty-modelled design at moderate unroll depth, which is why the op_q probe simulates with icarus instead).
- **Timestamp / author**: {{timestamp}}, Loom builder agent (issues #45 and #177).
"""
    rc.write_record(EXPERIMENT, rev, INPUTS, {"tool_versions": v}, body,
                    generator=__file__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
