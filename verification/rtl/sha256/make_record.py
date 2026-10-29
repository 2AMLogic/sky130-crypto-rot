#!/usr/bin/env python3
"""Verdict (and optionally record) for the SHA-256 core flow run by run.sh.

Reads flow/build/sha256/{sim,synth}.json (and million.json if --million-a ran).
Fails (exit 1) unless the simulation passed and the synthesis status is ok with
no latches, combinational loops or multi-driven nets. With no --check-only it
also writes an append-only record under
verification/records/sha256-core-sim-synth/records/. Standard library only.
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
EXPERIMENT = "sha256-core-sim-synth"
INPUTS = (
    "rtl/sha256/sha256_core.v",
    "verification/rtl/sha256/test_sha256_core.py",
    "verification/rtl/sha256/sim-request.json",
    "verification/rtl/sha256/sim-million-a-request.json",
    "verification/rtl/sha256/sim-negctl-request.json",
    "verification/rtl/sha256/sim-scrub-request.json",
    "verification/rtl/sha256/sim-scrub-negctl-request.json",
    "verification/rtl/sha256/synth-request.json",
    "verification/rtl/sha256/run.sh",
    "verification/rtl/sha256/make_record.py",
    "verification/model/sha256.py",
    "verification/model/vectorlib.py",
    "verification/vectors/SHA256ShortMsg.rsp",
    "verification/vectors/SHA256LongMsg.rsp",
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
    scrub = json.loads((args.out_dir / "scrub.json").read_text())
    mil_path = args.out_dir / "million.json"
    mil = json.loads(mil_path.read_text()) if mil_path.exists() else None
    st = syn["structural"]
    clean = st["latches"] == 0 and st["comb_loops"] == 0 and st["multi_driven"] == 0
    ok = sim["status"] == "pass" and scrub["status"] == "pass" and syn["status"] == "ok" and clean
    ok = ok and (mil is None or mil["status"] == "pass")
    mil_txt = "not run" if mil is None else mil["status"]
    print(f"sha256: simulation={sim['status']} million-a={mil_txt} synthesis={syn['status']} "
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
    mil_claim = (
        "The FIPS 180-4 million-`a` KAT **was run** (`--million-a`) and matched, one DUT instance, "
        "digest `cdc76e5c...112cd0`, 130 cycles after the last accepted byte (the last byte completes a block and the padding block follows)."
        if mil is not None else
        "The FIPS 180-4 million-`a` KAT was **not run** in this record (about 2M cycles, roughly "
        "10 minutes in Icarus; `run.sh --million-a` runs it). The spec section 2 KAT set "
        "(abc, 448-bit, million-a) is therefore **not claimed complete** by this record: `abc` and the "
        "448-bit CAVP vector ran, million-`a` did not."
    )
    log = (REPO / "verification/rtl/sha256/.klt/functional-verification/test_icarus.log")
    m = re.search(r"SUMMARY (.*)", log.read_text()) if log.exists() else None
    summary = m.group(1).strip() if m else "see sim.json"
    body = f"""<!-- record-meta
{json.dumps(meta, indent=2)}
-->

# Record {rid}

- **Record ID**: {rid}
- **Claim**: `rtl/sha256/sha256_core.v` (byte-serial in, one round per cycle, padding in hardware) produces the published SHA-256 digests for the vectors listed under Result, and takes 65 clock cycles per 512-bit block, as measured in the testbench. A correctness and cycle-count claim for the hash core only; it says nothing about key isolation, side channels or any timing at 50 MHz.
- **Design provenance**: RTL, pre-synthesis simulation (Icarus); the synthesis figure is the `klt synthesize` output for the same source. No gate-level simulation was run.
- **Run configuration**: `./scripts/setup-env.sh` then `./verification/rtl/sha256/run.sh --record{' --million-a' if mil else ''}`. Simulation: `klt functional-verification verification/rtl/sha256/sim-request.json` (engine icarus, `random_seed` 1, one DUT instance, no reset between messages). Synthesis: `klt synthesize verification/rtl/sha256/synth-request.json --pdk sky130A --pdk-root {args.pdk_root}`, liberty corner `tt_025C_1v80`, single corner, pre-P&R, cell area only, no clock target. No STA was run (needs a routed DEF).
- **Statistical convention**: deterministic; zero-mismatch pass/fail. Vectors: 65 CAVP `SHA256ShortMsg` and 64 CAVP `SHA256LongMsg` digests (provenance sidecars checked), FIPS 180-4 `abc`, the empty message, `a`*n for n in 55, 56, 63, 64, 119 against fixed independent digests, and boundary lengths 0, 1, 54-57, 63-65, 118-120, 127-129 against `verification/model/sha256.py`.
- **Result**: PASS. Simulation: {sim['passed_count']}/{sim['test_count']} tests passed ({summary}). Latency is defined in the bench as rising edges from the edge that accepts the transfer completing a block to `digest_valid`, and was 65 for the final block of every single-block-remaining message (130 when padding spills into a second block). {mil_claim} Negative control: `./verification/rtl/sha256/run.sh --negative-control` flips one K constant (`SHA256_NEG_CTRL`) and the bench fails, naming the first failing vector. Scrub: `sim-scrub-request.json` runs `test_scrub` ({scrub['passed_count']}/{scrub['test_count']} passed): a one-cycle `scrub` zeroes `w`, `hh`, `a`..`h`, `len`, `t` and `dvalid` (hierarchical read) from idle-after-message, mid-collect, mid-rounds at edges 1/17/40/64/65, the length-only spill block, the cycle `accept` is high, and back-to-back scrubs, and the next message then hashes to the model digest; the same `!rst_n || scrub` branch clears all of them, so reset and scrub share one list. Scrub negative control (`SHA256_NEG_SCRUB` omits `hh`) makes `test_scrub` fail. Only the scrub capability of the core is claimed; `scrub` is not wired from any HMAC or zeroize path here, and no netlist or formal check of the registers (P-2, P-9, P-10) was run. Synthesis: status `{syn['status']}`, {syn['instance_count']} instances, {syn['area_um2']} um2 ({syn['sequential_area_um2']} um2 sequential), no latches, combinational loops or multi-driven nets. Timing is `null`, so this record makes no timing claim; the spec section 7 figures (65 cycles at `ss_100C_1v60`, area) remain target, unmeasured against STA.
- **klt provenance**: klt `{prov['klt_version']}` pinned at `{versions['klt_pin']}`; pdk `{prov['pdk']['name']}` {prov['pdk']['version']}; liberty `{prov['deck']['name']}` {prov['deck']['content_hash']}; synthesis input {prov['input']['content_hash']}. Tool versions: Yosys {versions['yosys']} (yowasp-yosys {versions['yowasp_yosys']}, `yosys.wasm` {wasm}), Icarus Verilog {versions['icarus']}, cocotb {versions['cocotb']}, ciel {versions['ciel']}, Python {versions['python']}.
- **Links**: `rtl/sha256/sha256_core.v`, `verification/rtl/sha256/`, `docs/environment.md`, `spec/target-spec.md` section 2.
- **Timestamp / author**: {now:%Y-%m-%dT%H:%M:%SZ}, Loom builder agent (issue #61).
- **Supersedes**: none
"""
    out = REPO / "verification/records" / EXPERIMENT / "records" / f"{rid}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body)
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
