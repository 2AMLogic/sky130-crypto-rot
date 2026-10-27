#!/usr/bin/env python3
"""Verdict (and optionally record) for the AES-128 core flow run by run.sh.

Reads flow/build/aes/{sim,synth}.json.
Fails (exit 1) unless the simulation passed and the synthesis status is ok with
no latches, combinational loops or multi-driven nets. With no --check-only it
also writes an append-only record under
verification/records/aes-core-sim-synth/records/. Standard library only.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
import platform
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
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
    "scripts/setup-env.sh",
)


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def pin(name: str) -> str:
    for line in (REPO / "scripts/setup-env.sh").read_text().splitlines():
        if line.startswith(name + '="'):
            return line.split('"')[1]
    raise SystemExit(f"pin {name} not found in scripts/setup-env.sh")


def run(*cmd: str) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    text = (out.stdout + out.stderr).strip()
    return text.splitlines()[0] if text else "unknown"


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
    print(f"aes: simulation={sim['status']} synthesis={syn['status']} "
          f"latches={st['latches']} -> {'PASS' if ok else 'FAIL'}")
    if not ok:
        return 1
    if args.check_only:
        return 0

    sources = (args.pdk_root / "sky130A/SOURCES").read_text()
    if pin("CIEL_SKY130_VERSION") not in sources:
        raise SystemExit("PDK tree does not name the pinned open_pdks commit; refusing to record")
    rev = run("git", "-C", str(REPO), "rev-parse", "HEAD")
    if subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--"] + list(INPUTS[:-1]),
                      capture_output=True, text=True).stdout.strip():
        raise SystemExit("an input is modified relative to HEAD; commit it before recording")
    now = datetime.datetime.now(datetime.timezone.utc)
    rid = f"{now:%Y%m%d-%H%M%S}-{rev[:7]}"
    prov = syn["provenance"]
    venv_py = REPO / ".venv/bin/python3"
    wasm = run(str(venv_py), "-c",
               "import hashlib,os,yowasp_yosys as y;print('sha256:'+hashlib.sha256(open(os.path.join(os.path.dirname(y.__file__),'yosys.wasm'),'rb').read()).hexdigest())")
    versions = {
        "klt": prov["klt_version"],
        "klt_pin": pin("KLT_VERSION"),
        "yosys": syn["engine_version"],
        "yowasp_yosys": pin("YOWASP_YOSYS_VERSION"),
        "yosys_wasm": wasm,
        "icarus": sim["environment"]["engine_version"],
        "cocotb": sim["environment"]["cocotb_version"],
        "ciel": pin("CIEL_VERSION"),
        "python": platform.python_version(),
    }
    meta = {
        "record_id": rid,
        "experiment": EXPERIMENT,
        "supersedes": None,
        "git_revision": rev,
        "provenance": {
            "klt_version": prov["klt_version"],
            "pdk": {"name": prov["pdk"]["name"], "version": prov["pdk"]["version"]},
            "deck": {"name": prov["deck"]["name"], "content_hash": prov["deck"]["content_hash"]},
            "tool_versions": versions,
            "inputs": [{"path": p, "content_hash": sha256(REPO / p)} for p in INPUTS],
        },
    }
    log = (REPO / "verification/rtl/aes/.klt/functional-verification/test_icarus.log")
    m = re.search(r"SUMMARY (.*)", log.read_text()) if log.exists() else None
    summary = m.group(1).strip() if m else "see sim.json"
    body = f"""<!-- record-meta
{json.dumps(meta, indent=2)}
-->

# Record {rid}

- **Record ID**: {rid}
- **Claim**: `rtl/aes/aes_core.v` (AES-128, one round per cycle on a 128-bit state, on-the-fly key schedule, ECB, encrypt and decrypt) produces the published ciphertexts and plaintexts for the vectors listed under Result, and takes 11 clock cycles to encrypt and 21 to decrypt a block (decision record 0004), as measured in the testbench. A correctness and cycle-count claim for the cipher core only; it says nothing about key isolation (the formal properties are other issues), side channels or any timing at 50 MHz.
- **Design provenance**: RTL, pre-synthesis simulation (Icarus); the synthesis figure is the `klt synthesize` output for the same source. No gate-level simulation was run.
- **Run configuration**: `./scripts/setup-env.sh` then `./verification/rtl/aes/run.sh --record`. Simulation: `klt functional-verification verification/rtl/aes/sim-request.json` (engine icarus, `random_seed` 1, one DUT instance). Synthesis: `klt synthesize verification/rtl/aes/synth-request.json --pdk sky130A --pdk-root {args.pdk_root}`, liberty corner `tt_025C_1v80`, single corner, pre-P&R, cell area only, no clock target. No STA was run.
- **Statistical convention**: deterministic; zero-mismatch pass/fail. Vectors: FIPS 197 Appendix B and C.1 and SP 800-38A F.1.1/F.1.2 (provenance sidecars checked), each in both directions; 100 random key/block pairs in both directions against `verification/model/aes.py`; start while busy ignored; `block_out` zero while busy; `zeroize` mid-block (encrypt and decrypt) clearing the state, round-key and round-counter registers; round-key register clear at completion.
- **Result**: PASS. Simulation: {sim['passed_count']}/{sim['test_count']} tests passed ({summary}). Latency is measured in the bench as rising edges from the edge that accepts `start` through the edge after which `done` is seen high. Negative control: `./verification/rtl/aes/run.sh --negative-control` flips one S-box output bit (`AES_NEG_CTRL`) and the bench fails, naming the first failing vector. Synthesis: status `{syn['status']}`, {syn['instance_count']} instances, {syn['area_um2']} um2 ({syn['sequential_area_um2']} um2 sequential), no latches, combinational loops or multi-driven nets. Timing is `null`, so this record makes no timing claim; the spec figures remain target, unmeasured against STA.
- **klt provenance**: klt `{prov['klt_version']}` pinned at `{versions['klt_pin']}`; pdk `{prov['pdk']['name']}` {prov['pdk']['version']}; liberty `{prov['deck']['name']}` {prov['deck']['content_hash']}; synthesis input {prov['input']['content_hash']}. Tool versions: Yosys {versions['yosys']} (yowasp-yosys {versions['yowasp_yosys']}, `yosys.wasm` {wasm}), Icarus Verilog {versions['icarus']}, cocotb {versions['cocotb']}, ciel {versions['ciel']}, Python {versions['python']}.
- **Links**: `rtl/aes/aes_core.v`, `verification/rtl/aes/`, `docs/environment.md`, `spec/target-spec.md` section 1, `spec/decision-records/0004-aes-datapath-width.md`.
- **Timestamp / author**: {now:%Y-%m-%dT%H:%M:%SZ}, Loom builder agent (issue #43).
- **Supersedes**: none
"""
    out = REPO / "verification/records" / EXPERIMENT / "records" / f"{rid}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body)
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
