"""Shared helpers for the make_record.py scripts of the DRBG, TRNG-interface and
formal flows (standard library only). Writes an append-only record under
verification/records/<experiment>/records/ in the same layout as
verification/rtl/aes/make_record.py: a machine-readable `record-meta` comment,
then the claim, configuration and result.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import platform
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def pin(name: str) -> str:
    for line in (REPO / "scripts/setup-env.sh").read_text().splitlines():
        if line.startswith(name + '="'):
            return line.split('"')[1]
    raise SystemExit(f"pin {name} not found in scripts/setup-env.sh")


def first_line(*cmd: str) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError:
        return "unavailable"
    text = (out.stdout + out.stderr).strip()
    return text.splitlines()[0] if text else "unknown"


def require_clean_inputs(inputs) -> str:
    rev = first_line("git", "-C", str(REPO), "rev-parse", "HEAD")
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--"] + list(inputs),
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        raise SystemExit("an input is modified or untracked relative to HEAD; commit it before recording:\n" + dirty)
    return rev


def check_pdk(pdk_root: Path) -> None:
    sources = (pdk_root / "sky130A/SOURCES").read_text()
    if pin("CIEL_SKY130_VERSION") not in sources:
        raise SystemExit("PDK tree does not name the pinned open_pdks commit; refusing to record")


def tool_versions() -> dict:
    venv_py = REPO / ".venv/bin/python3"
    wasm = first_line(str(venv_py), "-c",
                      "import hashlib,os,yowasp_yosys as y;print('sha256:'+hashlib.sha256(open(os.path.join(os.path.dirname(y.__file__),'yosys.wasm'),'rb').read()).hexdigest())")
    return {
        "klt_revision": pin("KLT_REV"),
        "yowasp_yosys": pin("YOWASP_YOSYS_VERSION"),
        "yosys_wasm": wasm,
        "icarus": first_line("iverilog", "-V"),
        "cocotb": pin("COCOTB_VERSION"),
        "ciel": pin("CIEL_VERSION"),
        "python": platform.python_version(),
    }


def write_record(experiment: str, rev: str, inputs, meta_extra: dict, body: str) -> Path:
    now = datetime.datetime.now(datetime.timezone.utc)
    rid = f"{now:%Y%m%d-%H%M%S}-{rev[:7]}"
    meta = {
        "record_id": rid,
        "experiment": experiment,
        "supersedes": None,
        "git_revision": rev,
        "provenance": {**meta_extra,
                       "inputs": [{"path": p, "content_hash": sha256(REPO / p)} for p in inputs]},
    }
    text = f"<!-- record-meta\n{json.dumps(meta, indent=2)}\n-->\n\n# Record {rid}\n\n- **Record ID**: {rid}\n" + \
        body.replace("{rid}", rid).replace("{timestamp}", f"{now:%Y-%m-%dT%H:%M:%SZ}")
    out = REPO / "verification/records" / experiment / "records" / f"{rid}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f"wrote {out.relative_to(REPO)}")
    return out
