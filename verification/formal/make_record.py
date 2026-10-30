#!/usr/bin/env python3
"""Write the append-only record for verification/formal/run.sh.

Reads flow/build/formal/results.tsv (one line per sby task). Refuses to record
unless every task met its expectation. Standard library only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "flow/common"))
import record_lib as rc  # noqa: E402

EXPERIMENT = "drbg-trng-formal"
INPUTS = (
    "rtl/drbg/ctr_drbg.v",
    "rtl/trng_if/trng_if.v",
    "verification/formal/fv_drbg.v",
    "verification/formal/fv_p9.v",
    "verification/formal/p7_p8.sby",
    "verification/formal/p9.sby",
    "verification/formal/run.sh",
    "verification/formal/make_record.py",
    "flow/common/record_lib.py",
    "spec/key-isolation-properties.md",
    "scripts/setup-env.sh",
)

NOTES = {
    ("p7_p8.sby", "prove"): "P-7 and P-8 hold in every reachable state, unbounded (abc pdr), shipped interval 65536; the 17-bit counter is bounded by induction (`ctr_q <= interval + 1`), not by running 2^16 steps",
    ("p7_p8.sby", "reach_valid"): "vacuity: `blk_valid` is reachable (counterexample to `assert(!blk_valid)`)",
    ("p7_p8.sby", "reach_over"): "vacuity: `reseed_required` is reachable (interval 1)",
    ("p7_p8.sby", "neg_interval"): "RTL defect: one request too many allowed before RESEED_REQUIRED is caught by the P-8 assertions (interval 1)",
    ("p7_p8.sby", "neg_seeded"): "RTL defect: generate before instantiate is caught by the P-7 assertion",
    ("p9.sby", "bmc"): "P-9 bounded check, depth 30 from reset",
    ("p9.sby", "prove"): "P-9 unbounded (abc pdr)",
    ("p9.sby", "neg_bound"): "the same claim one cycle earlier fails: the 2-cycle response bound is tight, not slack",
    ("p9.sby", "reach_nonzero"): "vacuity: the registers can be non-zero before the alarm",
    ("p9.sby", "neg_zeroize"): "RTL defect: DRBG V surviving zeroize is caught",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    rows = [line.split("\t") for line in (args.out_dir / "results.tsv").read_text().splitlines() if line]
    if not rows or any(r[3] != "0" for r in rows):
        print("formal: not recording, a task did not meet its expectation", file=sys.stderr)
        return 1
    rev = rc.require_clean_inputs(INPUTS[:-1])
    v = rc.tool_versions()
    v["sby"] = rc.run(str(rc.REPO / ".venv/bin/yowasp-sby"), "--version")
    table = "\n".join(
        f"  | `{f}` | `{t}` | {s} | {e} | {fr} | {sec} | {NOTES.get((f, t), '')} |"
        for f, t, s, _rc, e, fr, sec in rows)
    body = f"""- **Claim**: properties P-7, P-8 and P-9 of `spec/key-isolation-properties.md` hold on the RTL of `rtl/drbg/ctr_drbg.v` and `rtl/trng_if/trng_if.v` as written in the task table below, with the AES engine abstracted to its busy/done handshake (an unconstrained latency of at least one cycle and an unconstrained result: the DRBG's control decisions never read the AES result). P-7: `blk_valid` implies seeded and not reseed-required. P-8: the reseed counter never exceeds interval + 1, a generate is never started above the interval, and the exhausted state persists until a reseed completes. P-9: if the synchronized alarm was high two cycles ago, DRBG `Key`/`V`, `chain`, df/Update working registers, the output register, the seed buffer and `out_ready` are zero (so zero within two core cycles of the synchronizer output, within the stated bound of 4, and held zero while the alarm stays asserted). RTL only: not re-proven on the synthesized netlist (issue #46), and not covering key slots, the AES core's own registers (issue #43), or the clock-domain timing of the synchronizer (modelled as an ordinary register chain at the core clock).
- **Design provenance**: RTL, formal (Yosys-internal engines through SymbiYosys).
- **Run configuration**: `./scripts/setup-env.sh` then `./verification/formal/run.sh --record`. Engines `abc pdr` (unbounded) and `abc bmc3` (bounded); `aigsmt none` because the provisioned sby has no SMT solver. Assertions are in the RTL under `ifdef FORMAL`; wrappers `fv_drbg.v` and `fv_p9.v` supply the environment (free commands, sizes, seeds, sibling pins and zeroize; reset/zeroize asserted in the first cycle, assertions gated on a first-zeroize/reset flag because the design has no reset of its own).
- **Result**: every task below met its expectation.

  | file | task | sby result | engine | counterexample frame | seconds | meaning |
  |---|---|---|---|---|---|---|
{table}

  Tasks named `reach_*` and `neg_*` are expected to FAIL (sby `expect fail`); their failure is the evidence that the passing tasks are not vacuous and that the checks can see a defect.
- **Tool gap**: the sby in the pinned venv (`yowasp-sby`) ships no SMT solver, so `smtbmc` engines, counterexample waveforms (`aigsmt`) and cover traces are unavailable, and it looks for `yosys-witness`/`yosys-smtbmc` by names the venv does not provide (shimmed under `flow/build/formal-bin/`). Filed on `2AMLogic/klayout-tools` as a generic tool gap.
- **Tool versions**: {v['sby']}, yowasp-yosys {v['yowasp_yosys']} (`yosys.wasm` {v['yosys_wasm']}), Python {v['python']}, klt pinned at `{v['klt_pin']}`.
- **Links**: `verification/formal/`, `spec/key-isolation-properties.md`, `rtl/drbg/`, `rtl/trng_if/`.
- **Timestamp / author**: {{timestamp}}, Loom builder agent (issue #45).
- **Supersedes**: none
"""
    rc.write_record(EXPERIMENT, rev, INPUTS[:-1], {"tool_versions": v}, body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
