#!/usr/bin/env python3
"""Verdict (and optionally record) for the crypto_rot_top flow run by run.sh.

Reads flow/build/crypto_rot_top/{sim,synth}.json. Fails (exit 1) unless the
simulation passed and the synthesis status is ok with no latches, combinational
loops or multi-driven nets. With no --check-only it also writes an append-only
record under verification/records/crypto-rot-top-sim/records/. Standard library
only.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "flow/common"))

import record_lib  # noqa: E402

NAME = "crypto_rot_top"
EXPERIMENT = "crypto-rot-top-sim"
# The inputs OUTSIDE this directory. The tracked files beside this generator
# are derived by record_lib.own_inputs(), and the shared flow helpers by
# shared_inputs(); neither is listed here (issues #124, #146).
INPUTS = (
    "rtl/sha256/sha256_core.v",
    "rtl/hmac/hmac_sha256.v",
    "rtl/keyladder/keyladder.v",
    "rtl/aes/aes_core.v",
    "rtl/drbg/ctr_drbg.v",
    "rtl/trng_if/trng_if.v",
    "rtl/drbg/drbg_top.v",
    "rtl/crypto_rot_top.v",
    "verification/model/aes.py",
    "verification/model/hmac_sha256.py",
    "verification/model/kdf.py",
    "verification/model/ctr_drbg.py",
    "verification/model/vectorlib.py",
    "verification/vectors/fips197.txt",
    "verification/vectors/rfc4231.txt",
    "verification/rtl/trng_if/trngmodel.py",
)


def body(ctx) -> str:
    sim, syn = ctx.sim, ctx.syn
    args = ctx.args
    return f"""- **Claim**: `rtl/crypto_rot_top.v` -- the top level integrating `rtl/aes/aes_core.v`, `rtl/hmac/hmac_sha256.v`, `rtl/keyladder/keyladder.v` and `rtl/drbg/drbg_top.v` (which embeds `trng_if`) behind the ratified register bus (0005) and register map (0009) -- runs the published AES and HMAC known-answer vectors end to end through the bus with slot keys (FIPS 197 both directions with the vector key loaded into a slot; RFC 4231 cases 1-3 with the case key loaded; case 4's 131-byte key is not bus-reachable in v1 and case 5 is truncated output, both out of scope by 0009), derives slot keys that match `verification/model/kdf.py` and produces DRBG output that matches `verification/model/ctr_drbg.py` seeded from the sibling stub's words; refuses every access class 0009 makes a violation (undefined address, write to a read-only register, write while the addressed engine is busy, read of a write-only location) with `err_o`, a zero read value, the `FAULT_CLS` bit and the ERROR pending bit; escalates (zeroize + `FAULT_ZEROIZED`) on a second violation within one operation and on any violation during key load; and performs every `target-spec.md` section 5 zeroize event (software `ZEROIZE`, synchronized TRNG alarm through `ALARM_ZEROIZED` and its recovery at the source, TRNG `gated` to `RESEED_REQUIRED` with keys kept, reset, and zeroize during an in-flight AES operation). The lifecycle FSM (`STATUS.STATE`), `ZCAUSE`, `FAULT_CLS`, sticky `IRQ_PEND` with the single mask and level `irq_o`, the DENY paths (a denied start runs no block) and the GEN_BITS > 128 refusal (ERR=3 without starting) are all checked. A correctness claim for this block's simulated behaviour only; it is not a key-isolation proof (the FORMAL sibling is #46's second child) and makes no side-channel, timing, entropy or certification claim (0008).
- **Design provenance**: RTL, pre-synthesis simulation (Icarus); the synthesis figure is the `klt synthesize` output for the same sources. No gate-level simulation was run.
- **Run configuration**: `./scripts/setup-env.sh` then `./verification/rtl/crypto_rot_top/run.sh --record`. Simulation: `klt functional-verification verification/rtl/crypto_rot_top/sim-request.json` (engine icarus, `random_seed` 1). Synthesis: `klt synthesize verification/rtl/crypto_rot_top/synth-request.json --pdk sky130A --pdk-root {args.pdk_root}`, liberty corner `tt_025C_1v80`, single corner, pre-P&R, cell area only, no clock target. No STA was run.
- **Statistical convention**: deterministic; zero-mismatch pass/fail. The bench drives the bus only (no hierarchical DUT access); the sibling pins come from the port-protocol stub `verification/rtl/trng_if/trngmodel.py` (40:1 clock ratio), as for the `drbg_top` bench. Golden values: the committed, provenance-checked FIPS 197 and RFC 4231 vector files for the published KATs; `verification/model/` for the derived-key AES/HMAC cross-checks and the DRBG (whose seed words are the stub's, so the model is seeded with exactly what the block saw). Key-adjacent readback is a directed sweep of all 128 word addresses against the set of 32-bit words of the root key, every slot key (derived and loaded), the seed words and the DRBG `Key`/`V` from the model. Negative controls: `./verification/rtl/crypto_rot_top/run.sh --negative-control` builds three variants and the bench fails on each: `TOP_NEG_ZEROIZE` (the zeroize level no longer reaches the key ladder), `TOP_NEG_FAULT` (an undefined-address access no longer records `FAULT_CLS` bit 0) and `KL_NEG_ZEROIZE` (the ladder's own control: slot 3 omitted from zeroize).
- **Result**: PASS. Simulation: {sim['passed_count']}/{sim['test_count']} tests passed ({ctx.summary}). Synthesis: status `{syn['status']}`, {syn['instance_count']} instances, {syn['area_um2']} um2 ({syn['sequential_area_um2']} um2 sequential, includes the AES, HMAC/SHA-256 and DRBG engines), no latches, combinational loops or multi-driven nets. Timing is `null`: no timing claim; the section 7 targets remain target, unmeasured. Not checked here: the committed netlist, the freshness check, the P-12 netlist re-proof and `klt signoff --attest 1` (sibling issue under #46); floorplan, P&R, GDS, LVS, STA (#47, #49, #50); and the formal properties P-1/P-2/P-11/P-12, which are stated against this bus front end but proved by the FORMAL sibling.
{ctx.klt_provenance}
- **Links**: `rtl/crypto_rot_top.v`, `verification/rtl/crypto_rot_top/`, `spec/target-spec.md` sections 5-6, `spec/decision-records/0005-register-bus.md`, `spec/decision-records/0009-register-map.md`, issue #87 (parent #46).
"""


def main() -> int:
    return record_lib.main(name=NAME, experiment=EXPERIMENT, inputs=INPUTS,
                           generator=__file__,
                           author="Loom builder agent (issue #87)", body=body)


if __name__ == "__main__":
    sys.exit(main())
