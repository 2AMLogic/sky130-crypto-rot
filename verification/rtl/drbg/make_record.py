#!/usr/bin/env python3
"""Verdict (and optionally record) for the DRBG flow run by run.sh.

Reads flow/build/drbg/{sim,cavp,synth}.json and the two SUMMARY files. Fails
(exit 1) unless both simulations passed and the synthesis status is ok with no
latches, combinational loops or multi-driven nets. Without --check-only it
also writes an append-only record under verification/records/drbg-sim-synth/.
The driver (argument parsing, verdict, guards, tool versions, record meta) is
record_lib.main(); the second simulation rides its extra_check hook. Standard
library only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "flow/common"))

import record_lib  # noqa: E402

NAME = "drbg"
EXPERIMENT = "drbg-sim-synth"
# The inputs OUTSIDE this directory. The tracked files beside this generator
# are derived by record_lib.own_inputs(), and the shared flow helpers by
# shared_inputs(); neither is listed here (issues #124, #146).
INPUTS = (
    "rtl/drbg/ctr_drbg.v",
    "rtl/drbg/drbg_top.v",
    "rtl/trng_if/trng_if.v",
    "rtl/aes/aes_core.v",
    "verification/model/ctr_drbg.py",
    "verification/model/aes.py",
    "verification/model/vectorlib.py",
    "verification/vectors/CTR_DRBG_pr_false.rsp",
)


def extra_check(out_dir: Path):
    """The second elaboration: the CAVP replay, plus both SUMMARY lines."""
    cavp = json.loads((out_dir / "cavp.json").read_text())
    return cavp["status"] == "pass", f" cavp={cavp['status']}", {
        "cavp": cavp,
        "shipped_summary": (out_dir / "summary-shipped.txt").read_text().strip(),
        "cavp_summary": (out_dir / "summary-cavp.txt").read_text().strip(),
    }


def body(ctx) -> str:
    sim, syn = ctx.sim, ctx.syn
    args = ctx.args
    cavp = ctx.extra["cavp"]
    shipped, cavp_s = ctx.extra["shipped_summary"], ctx.extra["cavp_summary"]
    return f"""- **Claim**: `rtl/drbg/ctr_drbg.v` (NIST SP 800-90A CTR_DRBG, AES-128, block-cipher derivation function, no prediction resistance; decision record 0002), driven through the AES forward cipher of `rtl/aes/aes_core.v`, reproduces `verification/model/ctr_drbg.py` and the published CAVP AES-128 use-df vectors in the two elaborations listed under Result. A correctness claim for the algorithm only; it says nothing about key isolation (the properties are in the `drbg-trng-formal` and `trng-if-sim` records), entropy, side channels or timing at 50 MHz.
- **Design provenance**: RTL, pre-synthesis simulation (Icarus). The synthesis figure is the `klt synthesize` output for `drbg_top` (DRBG, AES engine and the TRNG interface). No gate-level simulation was run.
- **Run configuration**: `./scripts/setup-env.sh` then `./verification/rtl/drbg/run.sh --record`. Simulation: `klt functional-verification` on `sim-request.json` (shipped elaboration) and `sim-cavp-request.json` (6/4-word elaboration), engine icarus, `random_seed` 1. Synthesis: `klt synthesize verification/rtl/drbg/synth-request.json --pdk sky130A --pdk-root {args.pdk_root}`, liberty corner `tt_025C_1v80`, single corner, pre-P&R, cell area only, no clock target. No STA was run.
- **Which vectors ran on which elaboration**:
  - Shipped 16/8-word elaboration (256-bit entropy + 256-bit nonce, 256-bit reseed, reseed interval 5 in the bench): NOT the CAVP vectors, because the df encodes the input length and the published records use 128-bit entropy and 64-bit nonce. Scored instead against `CtrDrbg` (`use_df=True`, 128-bit key) on directed (all-zero, all-ones, counting) and seeded-random 64-byte seeds: instantiate, reseed, generate of 128/1024/8/129/256/1/512/640 bits, Update after every request, the reseed counter up to and past the interval, size errors (0, 1025, 2047 bits), generate and reseed before instantiate (error status, no data) and after zeroize. `{shipped}`
  - 6/4-word elaboration (24-byte entropy||nonce, 16-byte reseed): the AES-128 use-df records of `CTR_DRBG_pr_false.rsp` (provenance sidecar checked) with personalization length 0 and both additional inputs empty, which are the only records inside the hardware's feature set (no personalization string, no additional input on generate or reseed): instantiate, reseed, generate-and-discard, generate, compare the second `ReturnedBits`. `{cavp_s}`
  - Not run: the other AES-128 use-df sections (non-empty personalization or additional input; unsupported by design, decision 0002), AES-256, no-df and 3KeyTDEA sections, prediction resistance.
- **Result**: PASS. Shipped elaboration {sim['passed_count']}/{sim['test_count']} tests, CAVP elaboration {cavp['passed_count']}/{cavp['test_count']} tests. Negative controls (`./verification/rtl/drbg/run.sh --negative-control`): a flipped bit of the df key constant, a flipped bit of V in Update, one request too many before RESEED_REQUIRED, and the CAVP replay on a corrupted Update each make the bench fail. Synthesis: status `{syn['status']}`, {syn['instance_count']} instances, {syn['area_um2']} um2 ({syn['sequential_area_um2']} um2 sequential), no latches, combinational loops or multi-driven nets. Timing is `null`: no timing claim.
{ctx.klt_provenance}
- **Links**: `rtl/drbg/`, `verification/rtl/drbg/`, `spec/decision-records/0002-drbg-construction.md`, `spec/target-spec.md` section 4.
"""


def main() -> int:
    return record_lib.main(name=NAME, experiment=EXPERIMENT, inputs=INPUTS,
                           generator=__file__,
                           author="Loom builder agent (issue #45)", body=body,
                           extra_check=extra_check)


if __name__ == "__main__":
    sys.exit(main())
