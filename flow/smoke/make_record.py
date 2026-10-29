#!/usr/bin/env python3
"""Verdict (and optionally record) for the smoke flow run by run.sh.

Reads flow/build/smoke/{sim,synth}.json. Fails (exit 1) unless the simulation
passed and the synthesis status is ok. With no --check-only it also writes an
append-only record under verification/records/smoke-synthesis-sim/records/.
Standard library only.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EXPERIMENT = "smoke-synthesis-sim"
INPUTS = (
    "flow/smoke/adder.v",
    "flow/smoke/test_adder.py",
    "flow/smoke/sim-request.json",
    "flow/smoke/synth-request.json",
    "flow/smoke/run.sh",
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
    return (out.stdout + out.stderr).strip().splitlines()[0] if (out.stdout + out.stderr).strip() else "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--pdk-root", type=Path, required=True)
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    sim = json.loads((args.out_dir / "sim.json").read_text())
    syn = json.loads((args.out_dir / "synth.json").read_text())
    ok = sim["status"] == "pass" and syn["status"] == "ok"
    print(f"smoke: simulation={sim['status']} synthesis={syn['status']} -> {'PASS' if ok else 'FAIL'}")
    if not ok:
        return 1
    if args.check_only:
        return 0

    sources = (args.pdk_root / "sky130A/SOURCES").read_text()
    if pin("CIEL_SKY130_VERSION") not in sources:
        raise SystemExit("PDK tree does not name the pinned open_pdks commit; refusing to record")
    rev = run("git", "-C", str(REPO), "rev-parse", "HEAD")
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
    tests = ", ".join(f"{t['name']} {t['status']}" for t in sim["tests"])
    body = f"""<!-- record-meta
{json.dumps(meta, indent=2)}
-->

# Record {rid}

- **Record ID**: {rid}
- **Claim**: The pinned environment in `docs/environment.md`, provisioned by `scripts/setup-env.sh`, runs the smoke flow end to end: a cocotb + Icarus test passes on the RTL of a registered 8-bit adder, and `klt synthesize` maps it to `sky130_fd_sc_hd`. A tooling claim only; it says nothing about any root-of-trust property.
- **Design provenance**: RTL (`flow/smoke/adder.v`), pre-synthesis simulation; synthesized netlist is the `klt synthesize` output for the same source.
- **Run configuration**: `./scripts/setup-env.sh` then `./flow/smoke/run.sh --record`. Simulation: `klt functional-verification flow/smoke/sim-request.json` (engine icarus, `random_seed` 1). Synthesis: `klt synthesize flow/smoke/synth-request.json --pdk sky130A --pdk-root {args.pdk_root}`, liberty corner `tt_025C_1v80`, no clock target. No STA was run (needs a routed DEF).
- **Statistical convention**: deterministic; 6 directed vectors plus 200 vectors from `random.Random(20261017)`; zero-mismatch pass/fail.
- **Result**: PASS. Simulation: {sim['passed_count']}/{sim['test_count']} tests passed ({tests}). Synthesis: status `{syn['status']}`, {syn['instance_count']} instances, {syn['area_um2']} um2 ({syn['sequential_area_um2']} um2 sequential), no latches, combinational loops or multi-driven nets. Timing is `null` (no clock target requested), so this record makes no timing claim.
- **klt provenance**: klt `{prov['klt_version']}` pinned at `{versions['klt_pin']}`; pdk `{prov['pdk']['name']}` {prov['pdk']['version']}; liberty `{prov['deck']['name']}` {prov['deck']['content_hash']}; synthesis input {prov['input']['content_hash']}. Tool versions: Yosys {versions['yosys']} (yowasp-yosys {versions['yowasp_yosys']}, `yosys.wasm` {wasm}), Icarus Verilog {versions['icarus']}, cocotb {versions['cocotb']}, ciel {versions['ciel']}, Python {versions['python']}.
- **Links**: `docs/environment.md`, `scripts/setup-env.sh`, `flow/smoke/`.
- **Timestamp / author**: {now:%Y-%m-%dT%H:%M:%SZ}, Loom builder agent (issue #4).
- **Supersedes**: none
"""
    out = REPO / "verification/records" / EXPERIMENT / "records" / f"{rid}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body)
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
