#!/usr/bin/env python3
"""Verdict (and optionally record) for the AES-128 core flow run by run.sh.

Reads flow/build/aes/{sim,synth}.json.
Fails (exit 1) unless the simulation passed and the synthesis status is ok with
no latches, combinational loops or multi-driven nets. With no --check-only it
also writes an append-only record under
verification/records/aes-core-sim-synth/records/. Standard library only.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "flow/common"))

import record_lib  # noqa: E402

NAME = "aes"
EXPERIMENT = "aes-core-sim-synth"
INPUTS = (
    "rtl/aes/aes_core.v",
    "verification/rtl/aes/test_aes_core.py",
    "verification/rtl/aes/sim-request.json",
    "verification/rtl/aes/sim-negctl-request.json",
    "verification/rtl/aes/synth-request.json",
    "verification/rtl/aes/run.sh",
    "verification/rtl/aes/make_record.py",
    "verification/model/aes.py",
    "verification/model/vectorlib.py",
    "verification/vectors/fips197.txt",
    "verification/vectors/sp800-38a-ecb.txt",
    "flow/common/core_flow.sh",
    "flow/common/record_lib.py",
    "scripts/setup-env.sh",
)


def body(ctx) -> str:
    sim, syn, prov = ctx.sim, ctx.syn, ctx.prov
    versions, wasm = ctx.versions, ctx.wasm
    summary = ctx.summary
    args = ctx.args
    return f"""- **Claim**: `rtl/aes/aes_core.v` (AES-128, one round per cycle on a 128-bit state, on-the-fly key schedule, ECB, encrypt and decrypt) produces the published ciphertexts and plaintexts for the vectors listed under Result, and takes 11 clock cycles to encrypt and 21 to decrypt a block (decision record 0004), as measured in the testbench. A correctness and cycle-count claim for the cipher core only; it says nothing about key isolation (the formal properties are other issues), side channels or any timing at 50 MHz.
- **Design provenance**: RTL, pre-synthesis simulation (Icarus); the synthesis figure is the `klt synthesize` output for the same source. No gate-level simulation was run.
- **Run configuration**: `./scripts/setup-env.sh` then `./verification/rtl/aes/run.sh --record`. Simulation: `klt functional-verification verification/rtl/aes/sim-request.json` (engine icarus, `random_seed` 1, one DUT instance). Synthesis: `klt synthesize verification/rtl/aes/synth-request.json --pdk sky130A --pdk-root {args.pdk_root}`, liberty corner `tt_025C_1v80`, single corner, pre-P&R, cell area only, no clock target. No STA was run.
- **Statistical convention**: deterministic; zero-mismatch pass/fail. Vectors: FIPS 197 Appendix B and C.1 and SP 800-38A F.1.1/F.1.2 (provenance sidecars checked), each in both directions; 100 random key/block pairs in both directions against `verification/model/aes.py`; start while busy ignored; `block_out` zero while busy; `zeroize` mid-block (encrypt and decrypt) clearing the state, round-key and round-counter registers; round-key register clear at completion.
- **Result**: PASS. Simulation: {sim['passed_count']}/{sim['test_count']} tests passed ({summary}). Latency is measured in the bench as rising edges from the edge that accepts `start` through the edge after which `done` is seen high. Negative control: `./verification/rtl/aes/run.sh --negative-control` flips one S-box output bit (`AES_NEG_CTRL`) and the bench fails, naming the first failing vector. Synthesis: status `{syn['status']}`, {syn['instance_count']} instances, {syn['area_um2']} um2 ({syn['sequential_area_um2']} um2 sequential), no latches, combinational loops or multi-driven nets. Timing is `null`, so this record makes no timing claim; the spec figures remain target, unmeasured against STA.
- **klt provenance**: klt `{prov['klt_version']}` from revision `{versions['klt_revision']}`; pdk `{prov['pdk']['name']}` {prov['pdk']['version']}; liberty `{prov['deck']['name']}` {prov['deck']['content_hash']}; synthesis input {prov['input']['content_hash']}. Tool versions: Yosys {versions['yosys']} (yowasp-yosys {versions['yowasp_yosys']}, `yosys.wasm` {wasm}), Icarus Verilog {versions['icarus']}, cocotb {versions['cocotb']}, ciel {versions['ciel']}, Python {versions['python']}.
- **Links**: `rtl/aes/aes_core.v`, `verification/rtl/aes/`, `docs/environment.md`, `spec/target-spec.md` section 1, `spec/decision-records/0004-aes-datapath-width.md`.
"""


def main() -> int:
    return record_lib.main(name=NAME, experiment=EXPERIMENT, inputs=INPUTS,
                           author="Loom builder agent (issue #43)", body=body)


if __name__ == "__main__":
    sys.exit(main())
