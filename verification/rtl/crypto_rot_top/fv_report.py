#!/usr/bin/env python3
"""The committed functional-verification report for the crypto_rot_top bench,
and the envelope that keeps it fresh (issue #296).

The pinned `klt functional-verification` (0.8.0) writes its JSON report with
the run's artifact paths absolute and with no input hashes at all -- the
`--check` flag and the `provenance` block are 0.9.x features -- so both the
committed evidence and its freshness check are this repo's own, on the
`netlist/check-fresh.sh` pattern (issue #88) rather than klt's:

  sync   run by run.sh after every simulation: write the report with the
         three absolute `environment.*` artifact paths rewritten
         repo-relative (2AMLogic/klayout-tools#5784; the pinned klt echoes
         the producing checkout into them), plus an envelope hashing every
         input the report's verdict depends on -- the request, each source
         it names (RTL and `tb_top.v`), the cocotb bench module klt does
         not hash, and the golden models/vectors the bench imports. When
         the committed pair already matches this run (same input hashes,
         same verdict and engine versions), the committed bytes are left
         untouched so a no-change rerun does not churn them.
  check  the CI half, no simulator and no PDK: recompute every envelope
         hash and the report's own. Exit 0 fresh, 3 stale, 1 hard error --
         the `klt netlist --check` convention check-fresh.sh follows too.

Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DIR = HERE.relative_to(REPO).as_posix()

REQUEST = "sim-request.json"
REPORT = HERE / "functional-verification-report.json"
ENVELOPE = HERE / "functional-verification-envelope.json"
SCHEMA = "sky130-crypto-rot.fv-report-envelope/1"

#: The environment.* fields klt 0.8.0 echoes as absolute producer paths.
ABS_FIELDS = ("results_xml", "test_log", "build_log")

#: What two runs of the same request can differ in without the inputs
#: differing: everything here is compared, real_time_s/sim_time_ns are not.
VERDICT_FIELDS = ("status", "test_count", "passed_count", "failed_count",
                  "skipped_count")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def repo_rel(path: Path) -> str:
    real = path.resolve()
    if not real.is_relative_to(REPO):
        raise SystemExit(f"fv-report: {path} resolves outside {REPO}; "
                         "the committed report must stay checkout-free")
    return real.relative_to(REPO).as_posix()


def klt_pin() -> str:
    if str(REPO / "flow/common") not in sys.path:
        sys.path.insert(0, str(REPO / "flow/common"))
    import record_lib  # noqa: E402
    return record_lib.pin("KLT_VERSION")


def freshness_inputs() -> list[str]:
    """Repo-relative paths whose bytes determine the report's verdict.

    The request and each source it names (klt's own --check scope, where the
    pinned klt has one), plus the cocotb bench module -- which klt hashes
    nowhere, at 0.8.0 or 0.9.x ("cocotb module contents ... are outside its
    scope") -- and the bench's outside-the-directory dependencies, taken from
    make_record.py's INPUTS so the two lists cannot drift (the issue #146
    rule). Sorted and deduplicated.
    """
    req = json.loads((HERE / REQUEST).read_text())
    paths = {f"{DIR}/{REQUEST}"}
    for src in req["sources"]:
        paths.add(repo_rel(HERE / src))
    paths.add(f"{DIR}/{req['testbench']['module']}.py")
    import make_record  # noqa: E402
    paths.update(make_record.INPUTS)
    return sorted(paths)


def _strings(doc) -> list[str]:
    out: list[str] = []
    def walk(node):
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, dict):
            for k, v in node.items():
                out.append(k)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(doc)
    return out


def normalize(doc: dict) -> list[str]:
    """Rewrite klt's absolute artifact paths repo-relative, in place.

    Returns the dotted fields rewritten. Refuses (not silently drops) a path
    that does not live under the repo, and refuses any other absolute path
    left anywhere in the document, so a future klt field of the same defect
    class cannot slip into committed evidence unremarked.
    """
    env = doc.setdefault("environment", {})
    rewritten = []
    for field in ABS_FIELDS:
        raw = env.get(field)
        if not isinstance(raw, str) or not raw:
            continue
        if Path(raw).is_absolute():
            env[field] = repo_rel(Path(raw))
            rewritten.append(f"environment.{field}")
    leaked = sorted(s for s in _strings(doc) if s.startswith("/"))
    if leaked:
        raise SystemExit("fv-report: report still carries absolute path(s) "
                         f"after normalization: {leaked}; file the klt gap "
                         "generically (2AMLogic/klayout-tools#5784 class) "
                         "and extend ABS_FIELDS")
    return rewritten


def _verdict(doc: dict) -> dict:
    env = doc.get("environment", {})
    return {**{f: doc.get(f) for f in VERDICT_FIELDS},
            "tests": sorted((t.get("name"), t.get("status")) for t in doc.get("tests", [])),
            "engine_version": env.get("engine_version"),
            "cocotb_version": env.get("cocotb_version")}


def _tree_diffs(env: dict) -> list[str]:
    want = env.get("inputs", [])
    diffs = []
    for entry in want:
        path = REPO / entry["path"]
        if not path.exists():
            diffs.append(f"{entry['path']}: missing from the tree")
        elif sha256(path) != entry["content_hash"]:
            diffs.append(f"{entry['path']}: envelope {entry['content_hash']}, "
                         f"tree {sha256(path)}")
    return diffs


def _load_pair():
    if not REPORT.exists() or not ENVELOPE.exists():
        return None, None, (f"committed {REPORT.name}/{ENVELOPE.name} pair "
                            "missing; run ./verification/rtl/crypto_rot_top/"
                            "run.sh --sim-only to write them")
    env = json.loads(ENVELOPE.read_text())
    if env.get("schema") != SCHEMA:
        return None, None, f"{ENVELOPE.name} carries schema {env.get('schema')!r}, not {SCHEMA!r}"
    doc = json.loads(REPORT.read_text())
    return env, doc, None


def _check_core() -> tuple[int, str, dict, dict]:
    """The simulator-free freshness verdict on the committed pair."""
    env, doc, err = _load_pair()
    if err:
        return 1, err, None, None
    regen = ("regenerate: ./verification/rtl/crypto_rot_top/run.sh --sim-only, "
             "then commit both files")
    if env.get("klt_version") != klt_pin():
        return 3, (f"STALE -- envelope pins klt {env.get('klt_version')}, the "
                   f"repo pins {klt_pin()}; a report from another klt is not "
                   f"evidence at this pin. {regen}"), env, doc
    diffs = _tree_diffs(env)
    if diffs:
        return 3, ("STALE -- committed report's inputs drifted:\n  "
                   + "\n  ".join(diffs) + f"\n{regen}"), env, doc
    if sha256(REPORT) != env.get("report_sha256"):
        return 3, (f"STALE -- {REPORT.name} does not hash to the envelope's "
                   f"report_sha256 (the pair disagrees). {regen}"), env, doc
    if doc.get("status") != "pass" or doc.get("passed_count") != doc.get("test_count"):
        return 3, (f"STALE -- committed report is {doc.get('status')} "
                   f"({doc.get('passed_count')}/{doc.get('test_count')}); "
                   f"committed evidence must be a passing run. {regen}"), env, doc
    n = len(env.get("inputs", []))
    return 0, (f"fresh ({REPORT.name} pass {doc.get('passed_count')}/"
               f"{doc.get('test_count')}, {n} input hashes match)"), env, doc


def verify_run(out_dir: Path) -> tuple[bool, str, dict]:
    """_check_core() plus: the committed report describes THIS run.

    What record_lib.main() calls for its verdict (and so for every record):
    input hashes alone cannot say the committed report is the suite that just
    passed -- the verdict, per-test statuses and engine/cocotb versions of
    the committed report must equal the fresh sim.json's, or the record would
    hash one run's evidence under another run's name.
    """
    code, msg, env, doc = _check_core()
    data = {}
    if code == 0:
        sim = json.loads((out_dir / "sim.json").read_text())
        if _verdict(doc) != _verdict(sim):
            code, msg = 3, ("STALE -- committed report's verdict differs from "
                            "this run's sim.json (tests, counts or engine "
                            "versions); regenerate and commit it"), None
    if code == 0:
        data = {"report": repo_rel(REPORT), "report_sha256": sha256(REPORT),
                "inputs": len(env.get("inputs", [])),
                "normalized_fields": env.get("normalized_fields", [])}
    text = " fv-report=fresh" if code == 0 else f" fv-report=stale ({msg})"
    return code == 0, text, data


def sync(sim_json: Path) -> int:
    """Write (or, when already fresh, leave) the committed pair."""
    raw = Path(sim_json).read_text()
    doc = json.loads(raw)
    if doc.get("status") != "pass":
        raise SystemExit(f"fv-report: refusing to commit a report with status "
                         f"{doc.get('status')!r}; the failing run is kept at "
                         f"{sim_json} for inspection")
    code, msg, env, committed = _check_core()
    if code == 0 and _verdict(committed) == _verdict(doc):
        print(f"fv-report: committed report already {msg}; left untouched")
        return 0
    fields = normalize(doc)
    text = json.dumps(doc, indent=2) + "\n"
    REPORT.write_text(text)
    ENVELOPE.write_text(json.dumps({
        "schema": SCHEMA,
        "report": REPORT.name,
        "report_sha256": sha256_bytes(text.encode()),
        "raw_report_sha256": sha256_bytes(raw.encode()),
        "normalized_fields": fields,
        "klt_version": klt_pin(),
        "engine_version": doc["environment"]["engine_version"],
        "cocotb_version": doc["environment"]["cocotb_version"],
        "inputs": [{"path": p, "content_hash": sha256(REPO / p)}
                   for p in freshness_inputs()],
    }, indent=2) + "\n")
    print(f"fv-report: wrote {repo_rel(REPORT)} and {repo_rel(ENVELOPE)} "
          f"({len(fields)} artifact path field(s) normalized, "
          f"{len(json.loads(ENVELOPE.read_text())['inputs'])} inputs hashed)")
    return 0


def check() -> int:
    code, msg, _, _ = _check_core()
    print("fv-report-fresh: " + msg,
          file=sys.stdout if code == 0 else sys.stderr)
    return code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="refresh the committed report+envelope "
                          "from a run's sim.json (what run.sh calls)")
    s.add_argument("sim_json", type=Path)
    sub.add_parser("check", help="freshness check, no simulator: 0 fresh, "
                     "3 stale, 1 hard error (what CI runs)")
    args = ap.parse_args(argv)
    return sync(args.sim_json) if args.cmd == "sync" else check()


if __name__ == "__main__":
    sys.exit(main())
