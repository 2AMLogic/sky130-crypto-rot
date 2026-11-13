"""Shared scaffolding for the per-core verification record makers.

Each verification/rtl/<core>/make_record.py supplies only its own data (name,
experiment, its own INPUTS -- the shared flow helpers are added by
shared_inputs(), not listed per core -- the claim/result prose as a body
callback, and an optional extra check such as a SHA-256 million-`a` result) and
calls main(). The verdict (sim passed, synthesis ok, no latches / comb loops /
multi-driven nets), the PDK-pin and dirty-input guards, the tool-version
collection, the shared klt-provenance bullet and the record-meta and record-id
emission live here so every core records the same way. Standard library only.
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

# The shared flow helpers every record implicitly depends on. No generator lists
# them in its own INPUTS: shared_inputs() adds them by name, so which files a
# record hashes and dirty-checks cannot drift between cores. SETUP_ENV is the
# one exception to "hashed and guarded": every record hashes it and reports its
# tool pins, but require_clean_inputs() exempts it from the dirty-input guard.
RECORD_LIB = "flow/common/record_lib.py"
CORE_FLOW = "flow/common/core_flow.sh"
SETUP_ENV = "scripts/setup-env.sh"

_SOURCES_CORE_FLOW = re.compile(r"^[ \t]*(?:source|\.)[ \t]+\S*" + re.escape(CORE_FLOW), re.M)

# A generated record filename: <YYYYMMDD>-<HHMMSS>-<7-hex> as write_record() builds
# it. The three hand-written independent-rerun records use a shorter shape and are
# deliberately not matched: only records this module wrote take part in the chain.
_RECORD_FILE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{7}\.md$")


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def pin(name: str) -> str:
    for line in (REPO / "scripts/setup-env.sh").read_text().splitlines():
        if line.startswith(name + '="'):
            return line.split('"')[1]
    raise SystemExit(f"pin {name} not found in scripts/setup-env.sh")


def run(*cmd: str) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError:
        return "unavailable"
    text = (out.stdout + out.stderr).strip()
    return text.splitlines()[0] if text else "unknown"


def wasm_hash() -> str:
    return run(str(REPO / ".venv/bin/python3"), "-c", _WASM_HASH)


def check_pdk(pdk_root: Path) -> None:
    sources = (pdk_root / "sky130A/SOURCES").read_text()
    if pin("CIEL_SKY130_VERSION") not in sources:
        raise SystemExit("PDK tree does not name the pinned open_pdks commit; refusing to record")


def _runs_core_flow(path: str) -> bool:
    """True if `path` is a flow's run.sh that sources flow/common/core_flow.sh."""
    return path.endswith("/run.sh") and bool(_SOURCES_CORE_FLOW.search((REPO / path).read_text()))


def shared_inputs(inputs) -> list:
    """`inputs` plus the shared flow helpers, which no generator lists by hand.

    record_lib.py and setup-env.sh are always added -- every generator imports the
    first, and tool_versions() reads every pin it reports out of the second.
    core_flow.sh is added when the flow's own run.sh (already one of `inputs`)
    sources it, so the record follows what the flow actually runs rather than a
    hand-copied line. Entries already present are not duplicated, so the result is
    idempotent.
    """
    out = list(inputs)
    extra = [CORE_FLOW] if any(_runs_core_flow(p) for p in out) else []
    for path in extra + [RECORD_LIB, SETUP_ENV]:
        if path not in out:
            out.append(path)
    return out


def require_clean_inputs(inputs) -> str:
    """HEAD revision, after refusing if any input is modified or untracked.

    The shared flow helpers are guarded too, whether or not `inputs` names them,
    with one exemption: scripts/setup-env.sh is hashed into every record but is
    not guarded. The exemption is applied here, by name, so it reads the same way
    for every generator instead of each caller slicing a positional entry off.
    """
    guarded = [p for p in shared_inputs(inputs) if p != SETUP_ENV]
    rev = run("git", "-C", str(REPO), "rev-parse", "HEAD")
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--"] + guarded,
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        raise SystemExit("an input is modified or untracked relative to HEAD; commit it before recording:\n" + dirty)
    return rev


def tool_versions() -> dict:
    """Pinned tool versions common to every flow; callers add what they measured."""
    return {
        "klt_pin": pin("KLT_VERSION"),
        "yowasp_yosys": pin("YOWASP_YOSYS_VERSION"),
        "yosys_wasm": wasm_hash(),
        "icarus": run("iverilog", "-V"),
        "cocotb": pin("COCOTB_VERSION"),
        "ciel": pin("CIEL_VERSION"),
        "python": platform.python_version(),
    }


def klt_provenance_bullet(prov: dict, versions: dict) -> str:
    """The record's `klt provenance` bullet, built once for every sim+synth core.

    Five generators carried a byte-identical (drbg's: near-identical) copy of this
    f-string, so a change to what the records say about their tools had to be made
    five times. main() exposes the result as ctx.klt_provenance; no generator
    writes the bullet itself. No trailing newline: a body interpolates it as a line.
    """
    return (
        f"- **klt provenance**: klt `{prov['klt_version']}` pinned at `{versions['klt_pin']}`; "
        f"pdk `{prov['pdk']['name']}` {prov['pdk']['version']}; "
        f"liberty `{prov['deck']['name']}` {prov['deck']['content_hash']}; "
        f"synthesis input {prov['input']['content_hash']}. "
        f"Tool versions: Yosys {versions['yosys']} (yowasp-yosys {versions['yowasp_yosys']}, "
        f"`yosys.wasm` {versions['yosys_wasm']}), Icarus Verilog {versions['icarus']}, "
        f"cocotb {versions['cocotb']}, ciel {versions['ciel']}, Python {versions['python']}."
    )


def previous_record(experiment: str) -> str | None:
    """Id of the newest record git already tracks for `experiment`, else None.

    This is the value of the record's `supersedes` field. Supersession here is
    positional -- "the record this one follows" -- not a claim that the new
    record repeats or widens the old one's coverage; see verification/README.md.

    Only tracked (committed or staged) files count, so an untracked leftover from
    an aborted run is never named. Ids sort chronologically by construction, so
    the newest is the lexically greatest. subprocess is used directly rather than
    run(), which swallows errors: a lookup that cannot be answered must refuse,
    not quietly report "no predecessor" and write a false claim into the trail.
    """
    rel = f"verification/records/{experiment}/records"
    try:
        out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "--", rel],
                             capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"cannot list tracked records under {rel}, refusing to record: {exc}")
    ids = sorted(name[:-3] for name in
                 (entry.rsplit("/", 1)[-1] for entry in out.stdout.split("\0") if entry)
                 if _RECORD_FILE.match(name))
    return ids[-1] if ids else None


def write_record(experiment: str, rev: str, inputs, meta_extra: dict, body: str) -> Path:
    """Append-only record: record-meta comment, then `body` (bullets from Claim on).

    The shared flow helpers are hashed in too, whether or not `inputs` names them.
    `{rid}` and `{timestamp}` in body are substituted.
    """
    supersedes = previous_record(experiment)
    inputs = shared_inputs(inputs)
    now = datetime.datetime.now(datetime.timezone.utc)
    rid = f"{now:%Y%m%d-%H%M%S}-{rev[:7]}"
    meta = {
        "record_id": rid,
        "experiment": experiment,
        "supersedes": supersedes,
        "git_revision": rev,
        "provenance": {**meta_extra,
                       "inputs": [{"path": p, "content_hash": sha256(REPO / p)} for p in inputs]},
    }
    text = f"<!-- record-meta\n{json.dumps(meta, indent=2)}\n-->\n\n# Record {rid}\n\n- **Record ID**: {rid}\n" + \
        body.replace("{rid}", rid).replace("{timestamp}", f"{now:%Y-%m-%dT%H:%M:%SZ}")
    # Appended after substitution and from the same value as the meta field, so no
    # body text can collide with it and the two can never disagree.
    text = (text if text.endswith("\n") else text + "\n") + \
        f"- **Supersedes**: {supersedes or 'none'}\n"
    out = REPO / "verification/records" / experiment / "records" / f"{rid}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f"wrote {out.relative_to(REPO)}")
    return out


def main(*, name, experiment, inputs, author, body, extra_check=None, argv=None) -> int:
    """Verdict, and unless --check-only an append-only record, for one core.

    name:        core directory under verification/rtl/ (also the verdict label)
    inputs:      repo-relative paths specific to this core, hashed into the
                 record. The shared flow helpers are added by shared_inputs()
                 and must not be listed here; of those, scripts/setup-env.sh is
                 hashed but exempt from the dirty-input guard
    author:      text after the timestamp in the record
    body:        callable(ctx) -> the record's bullets from Claim through Links.
                 ctx carries args, sim, syn, prov, versions, summary, the
                 extra_check data as ctx.extra, and the ready-made
                 ctx.klt_provenance bullet, which no body rebuilds
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

    check_pdk(args.pdk_root)
    rev = require_clean_inputs(inputs)
    prov = syn["provenance"]
    versions = tool_versions()
    versions = {
        "klt": prov["klt_version"],
        "klt_pin": versions.pop("klt_pin"),
        "yosys": syn["engine_version"],
        **versions,
        "icarus": sim["environment"]["engine_version"],
        "cocotb": sim["environment"]["cocotb_version"],
    }
    meta_extra = {
        "klt_version": prov["klt_version"],
        "pdk": {"name": prov["pdk"]["name"], "version": prov["pdk"]["version"]},
        "deck": {"name": prov["deck"]["name"], "content_hash": prov["deck"]["content_hash"]},
        "tool_versions": versions,
    }
    log = REPO / f"verification/rtl/{name}/.klt/functional-verification/test_icarus.log"
    m = re.search(r"SUMMARY (.*)", log.read_text()) if log.exists() else None
    ctx = SimpleNamespace(args=args, sim=sim, syn=syn, prov=prov, versions=versions,
                          klt_provenance=klt_provenance_bullet(prov, versions), extra=extra,
                          summary=m.group(1).strip() if m else "see sim.json")
    tail = f"- **Timestamp / author**: {{timestamp}}, {author}.\n"
    write_record(experiment, rev, inputs, meta_extra, body(ctx) + tail)
    return 0
