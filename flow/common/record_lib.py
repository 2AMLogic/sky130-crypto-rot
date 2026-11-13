"""Shared scaffolding for the per-core verification record makers.

Each verification/rtl/<core>/make_record.py supplies only its own data (name,
experiment, its own INPUTS -- the files OUTSIDE its directory; the files beside
it and the shared flow helpers are added by shared_inputs() from `generator`,
not listed per core -- the claim/result prose as a body callback, and an
optional extra check such as a SHA-256 million-`a` result) and calls main(). The
verdict (sim passed, synthesis ok, no latches / comb loops / multi-driven nets),
the PDK-pin and dirty-input guards, the tool-version collection and the
record-meta and record-id emission live here so every core records the same way.
Standard library only.
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
# them in its own INPUTS: shared_inputs() adds them, so which files a record
# hashes and dirty-checks cannot drift between cores. The files in a generator's
# OWN directory are derived the same way, by own_inputs() -- see its docstring.
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


def _git_lines(*args: str) -> list[str]:
    """NUL-separated output of a git command that must succeed, as a list.

    subprocess directly rather than run(), which swallows errors: a lookup that
    decides which files a record hashes must refuse when it cannot be answered,
    not quietly report an empty list and write a record over a short input set.
    """
    try:
        out = subprocess.run(["git", "-C", str(REPO), *args],
                             capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"cannot run `git {' '.join(args)}`, refusing to record: {exc}")
    return [entry for entry in out.stdout.split("\0") if entry]


def generator_dir(generator) -> str:
    """Repo-relative directory holding `generator` (a make_record.py path)."""
    here = Path(generator).resolve().parent
    try:
        return here.relative_to(REPO).as_posix()
    except ValueError:
        raise SystemExit(f"{generator} is outside {REPO}; refusing to record")


def own_inputs(generator) -> list[str]:
    """The tracked files sitting directly beside `generator`, sorted.

    In every flow directory each tracked file is one of that flow's record
    inputs -- the bench, its Verilog wrappers, every klt request, run.sh, the
    helper scripts, the generator itself -- so the rule is uniform and the list
    carries no information. It is therefore derived rather than hand-copied into
    each INPUTS, for the same reason shared_inputs() derives the shared helpers:
    a hand-copied list drifts (issue #146 found the hmac scrub negative-control
    request run by the bench but absent from its generator's INPUTS, so the next
    hmac record would have neither hashed nor dirty-checked it).

    Non-recursive: verification/formal/keyladder/ is a separate experiment with
    its own generator, and must not fold into verification/formal/'s inputs. The
    files a run generates (the trng_if klt requests, the klt scratch directory,
    the cocotb build) are gitignored, so they are untracked and stay out by
    construction; require_clean_inputs() refuses on any that is not.
    """
    here = generator_dir(generator)
    return sorted(path for path in _git_lines("ls-files", "-z", "--", here)
                  if path.rsplit("/", 1)[0] == here)


def _untracked_in(directory: str) -> list[str]:
    """Untracked, non-ignored entries directly inside `directory`, sorted.

    own_inputs() names only TRACKED files, so an uncommitted new file beside a
    generator would no longer trip the dirty guard the way a hand-listed one did.
    This closes that gap, and closes it wider: a stray file refuses the record
    whether or not anyone would have remembered to list it.
    """
    entries = _git_lines("ls-files", "--others", "--exclude-standard", "--directory",
                         "-z", "--", directory)
    return sorted(e for e in entries if e.rstrip("/").rsplit("/", 1)[0] == directory)


def shared_inputs(inputs, generator=None) -> list:
    """`inputs`, plus what no generator lists by hand: its own directory and the
    shared flow helpers.

    `generator` is the calling make_record.py (its `__file__`); when given, every
    tracked file beside it is added by own_inputs(), so `inputs` carries only the
    files OUTSIDE its directory -- the RTL sources, verification/model/*,
    verification/vectors/*, spec/*. record_lib.py is always added -- every
    generator imports it, and it is what hashes the inputs and writes the record.
    core_flow.sh is added when the flow's own run.sh (one of the derived
    own-directory files) sources it, so the record follows what the flow actually
    runs rather than a hand-copied line. Entries already present are not
    duplicated, and a trailing scripts/setup-env.sh stays last so the "last entry
    is exempt from the dirty-input guard" convention still holds.
    """
    out = list(inputs)
    tail = [out.pop()] if out and out[-1] == SETUP_ENV else []
    own = own_inputs(generator) if generator is not None else []
    extra = [CORE_FLOW] if any(_runs_core_flow(p) for p in out + own) else []
    for path in own + extra + [RECORD_LIB]:
        if path not in out:
            out.append(path)
    return out + tail


def require_clean_inputs(inputs, generator=None) -> str:
    """HEAD revision, after refusing if any input is modified or untracked.

    The shared flow helpers are guarded too, whether or not `inputs` names them,
    and when `generator` is given its whole directory is guarded: the derived
    own-directory inputs cover every tracked file there, and _untracked_in()
    covers the rest, so an uncommitted bench file refuses the record.
    """
    paths = shared_inputs(inputs, generator)
    rev = run("git", "-C", str(REPO), "rev-parse", "HEAD")
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--"] + list(paths),
                           capture_output=True, text=True).stdout.strip()
    stray = _untracked_in(generator_dir(generator)) if generator is not None else []
    if stray:
        dirty = "\n".join(([dirty] if dirty else []) + ["?? " + e for e in stray])
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


def write_record(experiment: str, rev: str, inputs, meta_extra: dict, body: str,
                 generator=None) -> Path:
    """Append-only record: record-meta comment, then `body` (bullets from Claim on).

    The shared flow helpers are hashed in too, whether or not `inputs` names them,
    and `generator`'s own directory is hashed in by shared_inputs().
    `{rid}` and `{timestamp}` in body are substituted.
    """
    supersedes = previous_record(experiment)
    inputs = shared_inputs(inputs, generator)
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


def main(*, name, experiment, inputs, generator, author, body, extra_check=None, argv=None) -> int:
    """Verdict, and unless --check-only an append-only record, for one core.

    name:        core directory under verification/rtl/ (also the verdict label)
    inputs:      repo-relative paths OUTSIDE this core's own directory, hashed
                 into the record; the last entry (scripts/setup-env.sh) is
                 excluded from the dirty-input guard. The files beside the
                 generator and the shared flow helpers are added by
                 shared_inputs() and must not be listed here
    generator:   the calling make_record.py (pass `__file__`); the tracked files
                 in its directory are the derived part of the input list
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

    check_pdk(args.pdk_root)
    rev = require_clean_inputs(inputs[:-1], generator)
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
                          wasm=versions["yosys_wasm"], extra=extra,
                          summary=m.group(1).strip() if m else "see sim.json")
    tail = f"- **Timestamp / author**: {{timestamp}}, {author}.\n"
    write_record(experiment, rev, inputs, meta_extra, body(ctx) + tail, generator)
    return 0
