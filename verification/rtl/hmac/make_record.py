#!/usr/bin/env python3
"""Verdict (and optionally record) for the HMAC-SHA-256 flow run by run.sh.

Reads flow/build/hmac/{sim,synth}.json.
Fails (exit 1) unless the simulation passed and the synthesis status is ok with
no latches, combinational loops or multi-driven nets. With no --check-only it
also writes an append-only record under
verification/records/hmac-sha256-sim-synth/records/. Standard library only.
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
EXPERIMENT = "hmac-sha256-sim-synth"
INPUTS = (
    "rtl/sha256/sha256_core.v",
    "rtl/hmac/hmac_sha256.v",
    "verification/rtl/hmac/test_hmac_sha256.py",
    "verification/rtl/hmac/sim-request.json",
    "verification/rtl/hmac/sim-negctl-request.json",
    "verification/rtl/hmac/synth-request.json",
    "verification/rtl/hmac/run.sh",
    "verification/rtl/hmac/make_record.py",
    "verification/model/hmac_sha256.py",
    "verification/model/vectorlib.py",
    "verification/vectors/rfc4231.txt",
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
    print(f"hmac_sha256: simulation={sim['status']} synthesis={syn['status']} "
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
    log = (REPO / "verification/rtl/hmac/.klt/functional-verification/test_icarus.log")
    m = re.search(r"SUMMARY (.*)", log.read_text()) if log.exists() else None
    summary = m.group(1).strip() if m else "see sim.json"
    kdf = re.search(r"kdf_shape_cycles_start_to_mac_valid=(\d+)", summary)
    kdf_cycles = kdf.group(1) if kdf else "see test log"
    body = f"""<!-- record-meta
{json.dumps(meta, indent=2)}
-->

# Record {rid}

- **Record ID**: {rid}
- **Claim**: `rtl/hmac/hmac_sha256.v` (HMAC-SHA-256 around one `rtl/sha256/sha256_core.v`, slot key up to 32 bytes plus a byte-stream key port for any length) produces the RFC 4231 tags for test cases 1, 2, 3, 4, 6 and 7 and matches `verification/model/hmac_sha256.py` on the random and boundary cases listed under Result. A correctness and cycle-count claim for the HMAC sequencer only; it says nothing about key isolation, side channels, or any timing at 50 MHz.
- **Design provenance**: RTL, pre-synthesis simulation (Icarus); the synthesis figure is the `klt synthesize` output for the same sources. No gate-level simulation was run.
- **Run configuration**: `./scripts/setup-env.sh` then `./verification/rtl/hmac/run.sh --record`. Simulation: `klt functional-verification verification/rtl/hmac/sim-request.json` (engine icarus, `random_seed` 1, one DUT instance, no reset between operations). Synthesis: `klt synthesize verification/rtl/hmac/synth-request.json --pdk sky130A --pdk-root {args.pdk_root}`, liberty corner `tt_025C_1v80`, single corner, pre-P&R, cell area only, no clock target. No STA was run.
- **Statistical convention**: deterministic; zero-mismatch pass/fail. Vectors: RFC 4231 cases 1-4, 6, 7 parsed from `verification/vectors/rfc4231.txt` (provenance checked; keys of at most 32 bytes run through both key ports, the 131-byte keys of cases 6 and 7 through the stream port); message lengths 0, 55, 56, 63, 64, 119 against key lengths 32, 64, 65; key lengths 0, 1, 31, 33, 63, 100, 128, 129, 200; 40 random key/message lengths with input stalls; all against the model, plus a `clear` abort followed by a good operation. RFC 4231 case 5 (truncation) is not applicable and is not run.
- **Result**: PASS. Simulation: {sim['passed_count']}/{sim['test_count']} tests passed ({summary}). The KDF message shape (52-byte message, 32-byte slot key) takes {kdf_cycles} clock cycles from the `start` edge to `mac_valid`, of which 4 x 65 = 260 are the four compressions of decision 0003 and the rest is the byte-serial feed of the ipad block, opad block and inner digest through the core's byte port plus the 52 message bytes. Negative control: `./verification/rtl/hmac/run.sh --negative-control` flips one opad bit (`HMAC_NEG_CTRL`, 0x5c to 0x5d) and the bench fails, naming the first failing vector. Synthesis: status `{syn['status']}`, {syn['instance_count']} instances, {syn['area_um2']} um2 ({syn['sequential_area_um2']} um2 sequential), no latches, combinational loops or multi-driven nets. Timing is `null`: no timing claim; the 50 MHz target remains target, unmeasured.
- **klt provenance**: klt `{prov['klt_version']}` pinned at `{versions['klt_pin']}`; pdk `{prov['pdk']['name']}` {prov['pdk']['version']}; liberty `{prov['deck']['name']}` {prov['deck']['content_hash']}; synthesis input {prov['input']['content_hash']}. Tool versions: Yosys {versions['yosys']} (yowasp-yosys {versions['yowasp_yosys']}, `yosys.wasm` {wasm}), Icarus Verilog {versions['icarus']}, cocotb {versions['cocotb']}, ciel {versions['ciel']}, Python {versions['python']}.
- **Links**: `rtl/hmac/hmac_sha256.v`, `verification/rtl/hmac/`, `docs/environment.md`, `spec/target-spec.md` section 2, `spec/decision-records/0003-kdf-construction.md`.
- **Timestamp / author**: {now:%Y-%m-%dT%H:%M:%SZ}, Loom builder agent (issue #54).
- **Supersedes**: none
"""
    out = REPO / "verification/records" / EXPERIMENT / "records" / f"{rid}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body)
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
