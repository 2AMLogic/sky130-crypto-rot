#!/usr/bin/env python3
"""Verdict (and optionally record) for the key ladder flow run by run.sh.

Reads flow/build/keyladder/{sim,synth}.json.
Fails (exit 1) unless the simulation passed and the synthesis status is ok with
no latches, combinational loops or multi-driven nets. With no --check-only it
also writes an append-only record under
verification/records/keyladder-sim-synth/records/. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "flow/common"))

import record_lib  # noqa: E402
EXPERIMENT = "keyladder-sim-synth"
INPUTS = (
    "rtl/sha256/sha256_core.v",
    "rtl/hmac/hmac_sha256.v",
    "rtl/keyladder/keyladder.v",
    "verification/rtl/keyladder/test_keyladder.py",
    "verification/rtl/keyladder/sim-request.json",
    "verification/rtl/keyladder/sim-negctl-mask-request.json",
    "verification/rtl/keyladder/sim-negctl-lock-request.json",
    "verification/rtl/keyladder/sim-negctl-zeroize-request.json",
    "verification/rtl/keyladder/synth-request.json",
    "verification/rtl/keyladder/run.sh",
    "verification/rtl/keyladder/make_record.py",
    "verification/model/kdf.py",
    "verification/model/hmac_sha256.py",
    "scripts/setup-env.sh",
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--pdk-root", type=Path, required=True)
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    sim = json.loads((args.out_dir / "sim.json").read_text())
    syn = json.loads((args.out_dir / "synth.json").read_text())
    st = syn["structural"]
    clean = st["latches"] == 0 and st["comb_loops"] == 0 and st["multi_driven"] == 0
    ok = sim["status"] == "pass" and syn["status"] == "ok" and clean
    print(f"keyladder: simulation={sim['status']} synthesis={syn['status']} "
          f"latches={st['latches']} -> {'PASS' if ok else 'FAIL'}")
    if not ok:
        return 1
    if args.check_only:
        return 0

    record_lib.check_pdk(args.pdk_root)
    rev = record_lib.require_clean_inputs(INPUTS[:-1])
    prov = syn["provenance"]
    versions = {
        **record_lib.tool_versions(),
        "klt": prov["klt_version"],
        "yosys": syn["engine_version"],
        "icarus": sim["environment"]["engine_version"],
        "cocotb": sim["environment"]["cocotb_version"],
    }
    wasm = versions["yosys_wasm"]
    meta_extra = {
        "klt_version": prov["klt_version"],
        "pdk": {"name": prov["pdk"]["name"], "version": prov["pdk"]["version"]},
        "deck": {"name": prov["deck"]["name"], "content_hash": prov["deck"]["content_hash"]},
        "tool_versions": versions,
    }
    log = (REPO / "verification/rtl/keyladder/.klt/functional-verification/test_icarus.log")
    m = re.search(r"SUMMARY (.*)", log.read_text()) if log.exists() else None
    summary = m.group(1).strip() if m else "see sim.json"
    cnt = re.search(r"derivations=(\d+)", summary)
    ndrv = cnt.group(1) if cnt else "see test log"
    body = f"""- **Claim**: `rtl/keyladder/keyladder.v` (4 derived 256-bit slots with per-slot use-mask, lock and chain depth; SP 800-108 counter-mode derivation over `rtl/hmac/hmac_sha256.v` in the 0003 layout; write-only software load; engine key release gated on the use-mask at the time of use; `zeroize` input) derives the slot values `verification/model/kdf.py` computes for root -> slot and root -> slot -> slot, releases a slot to an engine key output iff the engine's mask bit is set, and leaves every slot bit-identical on each listed refusal. A correctness claim for this block's behaviour in simulation; it is not a key-isolation proof (that is the FORMAL sibling), and it makes no side-channel, timing or certification claim.
- **Design provenance**: RTL, pre-synthesis simulation (Icarus); the synthesis figure is the `klt synthesize` output for the same sources. No gate-level simulation was run.
- **Run configuration**: `./scripts/setup-env.sh` then `./verification/rtl/keyladder/run.sh --record`. Simulation: `klt functional-verification verification/rtl/keyladder/sim-request.json` (engine icarus, `random_seed` 1). Synthesis: `klt synthesize verification/rtl/keyladder/synth-request.json --pdk sky130A --pdk-root {args.pdk_root}`, liberty corner `tt_025C_1v80`, single corner, pre-P&R, cell area only, no clock target. No STA was run.
- **Statistical convention**: deterministic; zero-mismatch pass/fail against the golden model. Cases: root -> slot for use_mask 0001, 0010, 0100, 1000, 1111 on every slot (masks without a direct engine path are checked through a child derivation; AES-only masks compare the upper 128 bits, the half the AES key port carries), root -> slot -> slot for three slot pairs, back-to-back and re-derivations, the full 16-mask x 4-slot x 3-engine permission matrix, the refusal cases (derive into a locked slot, from a locked parent, from a parent without KDF-parent, mask change, chain deeper than 2, never-derived parent, self-derive, lock of an empty slot, invalid root, command while busy, software load into a locked slot or with a changed mask), software load, and zeroize including four mid-derivation aborts. The CAVP `KDFCTR_gen.rsp` vectors are not used here: their fixed input data is not the 0003 layout, so the golden-model cross-check stands (0003 "Consequences").
- **Result**: PASS. Simulation: {sim['passed_count']}/{sim['test_count']} tests passed ({summary}); {ndrv} derivations completed. Negative controls: `./verification/rtl/keyladder/run.sh --negative-control` builds three variants (`KL_NEG_MASK`: HMAC mask bit not checked; `KL_NEG_LOCK`: lock not checked on write; `KL_NEG_ZEROIZE`: slot 3 omitted from zeroize) and the bench fails on each. Synthesis: status `{syn['status']}`, {syn['instance_count']} instances, {syn['area_um2']} um2 ({syn['sequential_area_um2']} um2 sequential, includes the HMAC and SHA-256 cores), no latches, combinational loops or multi-driven nets. Timing is `null`: no timing claim. Hand check of outputs: the only outputs derived from slot contents are `hmac_key` and `aes_key`; `slot_valid`, `slot_locked`, `busy`, `done_pulse`, `err_*` and `rel_deny` are status bits. Known limitation: `hmac_sha256` `clear` does not clear the SHA-256 core datapath registers (`w`, `hh`, `a`..`h`), so a derived key can remain there after a derivation or a zeroize; for the FORMAL sibling / the zeroize-completeness review (P-10).
- **klt provenance**: klt `{prov['klt_version']}` pinned at `{versions['klt_pin']}`; pdk `{prov['pdk']['name']}` {prov['pdk']['version']}; liberty `{prov['deck']['name']}` {prov['deck']['content_hash']}; synthesis input {prov['input']['content_hash']}. Tool versions: Yosys {versions['yosys']} (yowasp-yosys {versions['yowasp_yosys']}, `yosys.wasm` {wasm}), Icarus Verilog {versions['icarus']}, cocotb {versions['cocotb']}, ciel {versions['ciel']}, Python {versions['python']}.
- **Links**: `rtl/keyladder/keyladder.v`, `verification/rtl/keyladder/`, `spec/target-spec.md` section 3, `spec/decision-records/0003-kdf-construction.md`.
- **Timestamp / author**: {{timestamp}}, Loom builder agent (issue #55).
- **Supersedes**: none
"""
    record_lib.write_record(EXPERIMENT, rev, INPUTS, meta_extra, body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
