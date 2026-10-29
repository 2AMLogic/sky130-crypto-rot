"""Shared scaffolding for the per-core verification record makers.

Each verification/rtl/<core>/make_record.py supplies only its own data (name,
experiment, INPUTS, the claim/result prose as a body callback, and an optional
extra check such as a SHA-256 million-`a` result) and calls main(). The verdict
(sim passed, synthesis ok, no latches / comb loops / multi-driven nets), the
PDK-pin and dirty-input guards, the tool-version collection and the record-meta
and record-id emission live here so every core records the same way. Standard
library only.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import platform
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]

_WASM_HASH = ("import hashlib,os,yowasp_yosys as y;print('sha256:'+hashlib.sha256("
              "open(os.path.join(os.path.dirname(y.__file__),'yosys.wasm'),'rb').read()).hexdigest())")


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


def main(*, name, experiment, inputs, author, body, extra_check=None, argv=None) -> int:
    """Verdict, and unless --check-only an append-only record, for one core.

    name:        core directory under verification/rtl/ (also the verdict label)
    inputs:      repo-relative paths hashed into the record; the last entry
                 (scripts/setup-env.sh) is excluded from the dirty-input guard
    author:      text after the timestamp in the record
    body:        callable(ctx) -> the record's bullets from Claim through Links
    extra_check: optional callable(out_dir) -> (ok, verdict_text, data); the
                 verdict text is appended to the PASS/FAIL line and data is
                 exposed to body as ctx.extra
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--pdk-root", type=Path, required=True)
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args(argv)

    sim = json.loads((args.out_dir / "sim.json").read_text())
    syn = json.loads((args.out_dir / "synth.json").read_text())
    st = syn["structural"]
    clean = st["latches"] == 0 and st["comb_loops"] == 0 and st["multi_driven"] == 0
    ok = sim["status"] == "pass" and syn["status"] == "ok" and clean
    extra_ok, extra_txt, extra = extra_check(args.out_dir) if extra_check else (True, "", None)
    ok = ok and extra_ok
    print(f"{name}: simulation={sim['status']}{extra_txt} synthesis={syn['status']} "
          f"latches={st['latches']} -> {'PASS' if ok else 'FAIL'}")
    if not ok:
        return 1
    if args.check_only:
        return 0

    sources = (args.pdk_root / "sky130A/SOURCES").read_text()
    if pin("CIEL_SKY130_VERSION") not in sources:
        raise SystemExit("PDK tree does not name the pinned open_pdks commit; refusing to record")
    rev = run("git", "-C", str(REPO), "rev-parse", "HEAD")
    if subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--"] + list(inputs[:-1]),
                      capture_output=True, text=True).stdout.strip():
        raise SystemExit("an input is modified relative to HEAD; commit it before recording")
    now = datetime.datetime.now(datetime.timezone.utc)
    rid = f"{now:%Y%m%d-%H%M%S}-{rev[:7]}"
    prov = syn["provenance"]
    wasm = run(str(REPO / ".venv/bin/python3"), "-c", _WASM_HASH)
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
        "experiment": experiment,
        "supersedes": None,
        "git_revision": rev,
        "provenance": {
            "klt_version": prov["klt_version"],
            "pdk": {"name": prov["pdk"]["name"], "version": prov["pdk"]["version"]},
            "deck": {"name": prov["deck"]["name"], "content_hash": prov["deck"]["content_hash"]},
            "tool_versions": versions,
            "inputs": [{"path": p, "content_hash": sha256(REPO / p)} for p in inputs],
        },
    }
    log = REPO / f"verification/rtl/{name}/.klt/functional-verification/test_icarus.log"
    m = re.search(r"SUMMARY (.*)", log.read_text()) if log.exists() else None
    ctx = SimpleNamespace(args=args, sim=sim, syn=syn, prov=prov, versions=versions, wasm=wasm,
                          extra=extra, summary=m.group(1).strip() if m else "see sim.json")
    text = f"""<!-- record-meta
{json.dumps(meta, indent=2)}
-->

# Record {rid}

- **Record ID**: {rid}
{body(ctx)}- **Timestamp / author**: {now:%Y-%m-%dT%H:%M:%SZ}, {author}.
- **Supersedes**: none
"""
    out = REPO / "verification/records" / experiment / "records" / f"{rid}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f"wrote {out.relative_to(REPO)}")
    return 0
