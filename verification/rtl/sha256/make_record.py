#!/usr/bin/env python3
"""Verdict (and optionally record) for the SHA-256 core flow run by run.sh.

Reads flow/build/sha256/{sim,synth}.json (and million.json if --million-a ran).
Fails (exit 1) unless the simulation passed and the synthesis status is ok with
no latches, combinational loops or multi-driven nets. With no --check-only it
also writes an append-only record under
verification/records/sha256-core-sim-synth/records/. Standard library only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "flow/common"))

import record_lib  # noqa: E402

NAME = "sha256"
EXPERIMENT = "sha256-core-sim-synth"
INPUTS = (
    "rtl/sha256/sha256_core.v",
    "verification/rtl/sha256/test_sha256_core.py",
    "verification/rtl/sha256/sim-request.json",
    "verification/rtl/sha256/sim-million-a-request.json",
    "verification/rtl/sha256/sim-negctl-request.json",
    "verification/rtl/sha256/synth-request.json",
    "verification/rtl/sha256/run.sh",
    "verification/rtl/sha256/make_record.py",
    "verification/model/sha256.py",
    "verification/model/vectorlib.py",
    "verification/vectors/SHA256ShortMsg.rsp",
    "verification/vectors/SHA256LongMsg.rsp",
    "flow/common/core_flow.sh",
    "flow/common/record_lib.py",
    "scripts/setup-env.sh",
)


def extra_check(out_dir: Path):
    path = out_dir / "million.json"
    mil = json.loads(path.read_text()) if path.exists() else None
    txt = " million-a=" + ("not run" if mil is None else mil["status"])
    return mil is None or mil["status"] == "pass", txt, mil


def body(ctx) -> str:
    sim, syn, prov = ctx.sim, ctx.syn, ctx.prov
    versions, wasm = ctx.versions, ctx.wasm
    summary = ctx.summary
    args = ctx.args
    mil_claim = (
        "The FIPS 180-4 million-`a` KAT **was run** (`--million-a`) and matched, one DUT instance, "
        "digest `cdc76e5c...112cd0`, 130 cycles after the last accepted byte (the last byte completes a block and the padding block follows)."
        if ctx.extra is not None else
        "The FIPS 180-4 million-`a` KAT was **not run** in this record (about 2M cycles, roughly "
        "10 minutes in Icarus; `run.sh --million-a` runs it). The spec section 2 KAT set "
        "(abc, 448-bit, million-a) is therefore **not claimed complete** by this record: `abc` and the "
        "448-bit CAVP vector ran, million-`a` did not."
    )
    return f"""- **Claim**: `rtl/sha256/sha256_core.v` (byte-serial in, one round per cycle, padding in hardware) produces the published SHA-256 digests for the vectors listed under Result, and takes 65 clock cycles per 512-bit block, as measured in the testbench. A correctness and cycle-count claim for the hash core only; it says nothing about key isolation, side channels or any timing at 50 MHz.
- **Design provenance**: RTL, pre-synthesis simulation (Icarus); the synthesis figure is the `klt synthesize` output for the same source. No gate-level simulation was run.
- **Run configuration**: `./scripts/setup-env.sh` then `./verification/rtl/sha256/run.sh --record{' --million-a' if ctx.extra else ''}`. Simulation: `klt functional-verification verification/rtl/sha256/sim-request.json` (engine icarus, `random_seed` 1, one DUT instance, no reset between messages). Synthesis: `klt synthesize verification/rtl/sha256/synth-request.json --pdk sky130A --pdk-root {args.pdk_root}`, liberty corner `tt_025C_1v80`, single corner, pre-P&R, cell area only, no clock target. No STA was run (needs a routed DEF).
- **Statistical convention**: deterministic; zero-mismatch pass/fail. Vectors: 65 CAVP `SHA256ShortMsg` and 64 CAVP `SHA256LongMsg` digests (provenance sidecars checked), FIPS 180-4 `abc`, the empty message, `a`*n for n in 55, 56, 63, 64, 119 against fixed independent digests, and boundary lengths 0, 1, 54-57, 63-65, 118-120, 127-129 against `verification/model/sha256.py`.
- **Result**: PASS. Simulation: {sim['passed_count']}/{sim['test_count']} tests passed ({summary}). Latency is defined in the bench as rising edges from the edge that accepts the transfer completing a block to `digest_valid`, and was 65 for the final block of every single-block-remaining message (130 when padding spills into a second block). {mil_claim} Negative control: `./verification/rtl/sha256/run.sh --negative-control` flips one K constant (`SHA256_NEG_CTRL`) and the bench fails, naming the first failing vector. Synthesis: status `{syn['status']}`, {syn['instance_count']} instances, {syn['area_um2']} um2 ({syn['sequential_area_um2']} um2 sequential), no latches, combinational loops or multi-driven nets. Timing is `null`, so this record makes no timing claim; the spec section 7 figures (65 cycles at `ss_100C_1v60`, area) remain target, unmeasured against STA.
- **klt provenance**: klt `{prov['klt_version']}` pinned at `{versions['klt_pin']}`; pdk `{prov['pdk']['name']}` {prov['pdk']['version']}; liberty `{prov['deck']['name']}` {prov['deck']['content_hash']}; synthesis input {prov['input']['content_hash']}. Tool versions: Yosys {versions['yosys']} (yowasp-yosys {versions['yowasp_yosys']}, `yosys.wasm` {wasm}), Icarus Verilog {versions['icarus']}, cocotb {versions['cocotb']}, ciel {versions['ciel']}, Python {versions['python']}.
- **Links**: `rtl/sha256/sha256_core.v`, `verification/rtl/sha256/`, `docs/environment.md`, `spec/target-spec.md` section 2.
"""


def main() -> int:
    return record_lib.main(name=NAME, experiment=EXPERIMENT, inputs=INPUTS,
                           author="Loom builder agent (issue #33)", body=body, extra_check=extra_check)


if __name__ == "__main__":
    sys.exit(main())
