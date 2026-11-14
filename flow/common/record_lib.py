"""Shared scaffolding for the per-core verification record makers.

Each verification/rtl/<core>/make_record.py supplies only its own data (name,
experiment, its own INPUTS -- the files OUTSIDE its directory; the files beside
it and the shared flow helpers are added by shared_inputs() from `generator`,
not listed per core -- the claim/result prose as a body callback, and an
optional extra check such as a SHA-256 million-`a` result) and calls main(). The
verdict (sim passed, synthesis ok, no latches / comb loops / multi-driven nets),
the PDK-pin and dirty-input guards, the tool-version collection, the shared
klt-provenance bullet and the record-meta and record-id emission live here so
every core records the same way. Standard library only.
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
# The files in a generator's OWN directory are derived the same way, by
# own_inputs() -- see its docstring.
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
    verification/vectors/*, spec/*. record_lib.py and setup-env.sh are always
    added by name -- every generator imports the first, and tool_versions() reads
    every pin it reports out of the second. core_flow.sh is added when the flow's
    own run.sh (one of the derived own-directory files) sources it, so the record
    follows what the flow actually runs rather than a hand-copied line. Entries
    already present are not duplicated, so the result is idempotent, and
    setup-env.sh lands last, after the derived own-directory files and the other
    shared helpers.
    """
    out = list(inputs)
    own = own_inputs(generator) if generator is not None else []
    extra = [CORE_FLOW] if any(_runs_core_flow(p) for p in out + own) else []
    for path in own + extra + [RECORD_LIB, SETUP_ENV]:
        if path not in out:
            out.append(path)
    return out


def require_clean_inputs(inputs, generator=None) -> str:
    """HEAD revision, after refusing if any input is modified or untracked.

    The shared flow helpers are guarded too, whether or not `inputs` names them,
    and when `generator` is given its whole directory is guarded: the derived
    own-directory inputs cover every tracked file there, and _untracked_in()
    covers the rest, so an uncommitted bench file refuses the record. One
    exemption: scripts/setup-env.sh is hashed into every record but is not
    guarded. The exemption is applied here, by name, so it reads the same way for
    every generator instead of each caller slicing a positional entry off.
    """
    guarded = [p for p in shared_inputs(inputs, generator) if p != SETUP_ENV]
    rev = run("git", "-C", str(REPO), "rev-parse", "HEAD")
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--"] + guarded,
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


def open_pdks_revision(pdk_root: Path) -> str:
    """The open_pdks revision the installed sky130A tree names in its SOURCES.

    check_pdk() already refuses a tree whose SOURCES does not name the pinned
    commit, so by the time a record is written this is that commit -- it is read
    back rather than printed from the pin so the record states what was on disk.
    """
    for line in (pdk_root / "sky130A/SOURCES").read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "open_pdks":
            return parts[1]
    raise SystemExit(f"{pdk_root}/sky130A/SOURCES names no open_pdks revision")


#: The klayout-tools issues for the two tool gaps the gate-level mode meets,
#: linked from every gate-level record per this repo's friction protocol.
#:
#: #4196 -- a `klt synthesize` request cannot set a preprocessor define, so the
#: negative control's `ifdef cannot be applied at synthesis through the
#: request. Already filed and closed COMPLETED upstream (2026-10-27): later klt
#: has a `defines` key, so this repo meets it only through its KLT_VERSION pin,
#: and a pin bump retires the generated wrapper. Linked, not re-filed.
#:
#: #5684 -- `klt synthesize` and `klt functional-verification` do not compose:
#: simulating a synthesis run's own netlist means hand-rendering a request
#: around a per-run path, including the hash check that makes the verdict mean
#: anything. Filed from this work (the gap is the tool's, described there
#: without this design's detail).
_KLT_DEFINES_GAP = "#4196"
_KLT_CHAIN_GAP = "#5684"

#: The Design-provenance text every sim+synth record shared verbatim before
#: issue #179, and still the whole of it when no gate-level run happened.
_RTL_PROVENANCE = ("RTL, pre-synthesis simulation (Icarus); the synthesis figure is "
                   "the `klt synthesize` output for the same source.")


def gate_level_bullets(gate: dict | None, pdk_root: Path, name: str) -> tuple[str, str]:
    """``(provenance text, gate-level bullet)`` for one core's record.

    Both cores say exactly the same things about a gate-level run -- what it
    simulated, which cell models, which delay model, that it is pre-layout with
    no SDF -- so the text lives here for the same reason
    klt_provenance_bullet() does: five near-identical copies of a claim about
    the tools is five places to update when the claim changes.

    ``gate`` is flow/build/<core>/gate.json, written by core_flow_gate(), or
    None when no gate-level run happened. In that case the provenance text is
    byte-for-byte the one the records carried before issue #179, ending "No
    gate-level simulation was run.", and the bullet is the empty string: a
    record never implies a netlist simulation it does not have.

    The cell-model hashes are computed here, at record time, from the paths the
    request actually named. They are NOT copied from any pin or prose: the
    models are outside the repo, so they are not in the record's dirty-checked
    `inputs` list, and the hash is the only thing that identifies which models
    the simulation elaborated.
    """
    if gate is None:
        return f"{_RTL_PROVENANCE} No gate-level simulation was run.", ""
    models = ", ".join(f"`{Path(p).name}` {sha256(Path(p))}" for p in gate["cell_models"])
    # `tc`, not `name`: `name` is the core, and a genexp variable that shadowed
    # it would read as though the negative-control command below named a testcase.
    ran = ", ".join(
        f"`{tc}` ({run['passed_count']}/{run['test_count']} passed, "
        f"{run['tests'][0]['sim_time_ns'] / 1000:.1f} us simulated)"
        for tc, run in sorted(gate["testcases"].items()))
    skipped = ("; **not run at gate level**: " +
               ", ".join(f"`{k}` ({v})" for k, v in sorted(gate["excluded"].items()))
               if gate["excluded"] else
               "; no testcase of this bench was left out of the gate-level run")
    defines = ", ".join(f"`{k}`" if v is None else f"`{k}` = `{v}`"
                        for k, v in gate["defines"].items())
    return (
        f"{_RTL_PROVENANCE} The same bench was then re-run against that netlist "
        "(see Gate-level simulation below), so the vectors are claimed on the "
        "mapped gates and not only on the RTL.",
        f"- **Gate-level simulation**: the same cocotb bench, unmodified, against "
        f"the synthesized netlist -- `{gate['netlist_path']}`, "
        f"sha256:{gate['netlist_sha256']}, {gate['instance_count']} "
        f"`sky130_fd_sc_hd` instances -- read back from this run's own `klt "
        f"synthesize` report and re-hashed before the request was built, so a "
        f"stale netlist in `flow/build/` cannot be simulated in its place. That "
        f"path is per-run scratch (`klt synthesize` claims a fresh "
        f"`.klt/synthesize/run-<uuid>/` each time) and is gitignored, so the "
        f"sha256 above, not the path, is the netlist's identity. Cell "
        f"models: {models}, from the `sky130A` install at open_pdks "
        f"`{open_pdks_revision(pdk_root)}`; the vendored "
        f"`verification/gate-level/common/sky130_fd_sc_hd_sim_defines.v` is "
        f"**not** used -- the pinned klt forwards `options.defines` itself. "
        f"Delay model: {defines} -- the PDK's zero-delay behavioural models "
        f"(Icarus implements neither `$setuphold` nor `$recrem`'s "
        f"delayed-signal outputs, so the `specify` timing models simulate as "
        f"all-`x`), with each flop's output one `#1` = 1 ns off the clock edge "
        f"that produced it, against this bench's 20 ns clock. **Pre-layout, no "
        f"SDF back-annotation**: `options.sdf` is "
        f"`{json.dumps(gate['sdf'])}`, so this is a "
        f"functional check of the mapped gates and makes NO timing claim; the "
        f"SDF-annotated post-route run is issue #82. Status "
        f"`{gate['status']}` -- ran {ran}{skipped}. Gate-level negative "
        f"control: `./verification/rtl/{name}/run.sh --gate-level "
        f"--negative-control` synthesizes the corrupted build and runs the "
        f"bench on THAT netlist, and exits 0 only because the bench caught it "
        f"-- `klt` exited non-zero AND the cocotb results XML named the first "
        f"failing vector, the two-part test of issue #151. The corruption is a "
        f"`` `ifdef `` in the RTL and a netlist carries no preprocessor, so it "
        f"has to be applied at synthesis -- and the pinned `klt synthesize` "
        f"request has no `defines` key (the pin's allowed keys are schema, "
        f"engine, sources, hdl_toplevel, pdk, constraints, structural, "
        f"baseline, arithmetic, run_id, outputs, parameters). The flow "
        f"therefore generates a wrapper that defines the macro and "
        f"`` `include ``s the RTL, and uses it as that synthesis run's only "
        f"source. Per this repo's friction protocol that tool gap is "
        f"`2AMLogic/klayout-tools` {_KLT_DEFINES_GAP}, which is already filed "
        f"and closed COMPLETED upstream: a `synthesize` `defines` key exists "
        f"in later klt, so the wrapper is a consequence of the "
        f"`KLT_VERSION` pin, not of an open gap, and a pin bump retires it. "
        f"The second gap this mode meets -- that `klt synthesize` and `klt "
        f"functional-verification` do not compose, so simulating a synthesis "
        f"run's own netlist means hand-rendering a request around a per-run "
        f"path, hash check included -- was not already filed and is "
        f"`2AMLogic/klayout-tools` {_KLT_CHAIN_GAP}.\n")


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
                 into the record. The files beside the generator and the shared
                 flow helpers are added by shared_inputs() and must not be
                 listed here; of those, scripts/setup-env.sh is hashed but
                 exempt from the dirty-input guard
    generator:   the calling make_record.py (pass `__file__`); the tracked files
                 in its directory are the derived part of the input list
    author:      text after the timestamp in the record
    body:        callable(ctx) -> the record's bullets from Claim through Links.
                 ctx carries args, sim, syn, prov, versions, summary, the
                 extra_check data as ctx.extra, and the ready-made
                 ctx.klt_provenance bullet, which no body rebuilds. For the
                 gate-level mode (issue #179) it also carries ctx.gate (the
                 parsed flow/build/<core>/gate.json, or None), and two
                 ready-made pieces of text no body rebuilds either:
                 ctx.gate_provenance, the Design-provenance sentence, which
                 still reads "No gate-level simulation was run." when there
                 was none; and ctx.gate_level, the Gate-level-simulation
                 bullet, which is the empty string when there was none
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
    # gate.json exists only when run.sh --gate-level ran; core_flow_finish
    # removes it first, so it is always this run's. A gate-level failure fails
    # the verdict: a netlist that does not compute the vectors is not a PASS
    # whatever the RTL did.
    gate_path = args.out_dir / "gate.json"
    gate = json.loads(gate_path.read_text()) if gate_path.exists() else None
    gate_txt = "" if gate is None else f" gate-level={gate['status']}"
    ok = ok and (gate is None or gate["status"] == "pass")
    extra_ok, extra_txt, extra = extra_check(args.out_dir) if extra_check else (True, "", None)
    ok = ok and extra_ok
    print(f"{name}: simulation={sim['status']}{extra_txt}{gate_txt} synthesis={syn['status']} "
          f"latches={st['latches']} -> {'PASS' if ok else 'FAIL'}")
    if not ok:
        return 1
    if args.check_only:
        return 0

    check_pdk(args.pdk_root)
    rev = require_clean_inputs(inputs, generator)
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
    if gate is not None:
        # The cell models are outside the repo, so they cannot ride in the
        # record's `inputs` list (repo-relative, dirty-checked). They go in the
        # provenance block instead, hashed here at record time.
        meta_extra["gate_level"] = {
            "netlist_path": gate["netlist_path"],
            "netlist_sha256": gate["netlist_sha256"],
            "instance_count": gate["instance_count"],
            "cell_models": [{"path": p, "content_hash": sha256(Path(p))}
                            for p in gate["cell_models"]],
            "open_pdks": open_pdks_revision(args.pdk_root),
            "defines": gate["defines"],
            "sdf": gate["sdf"],
            "status": gate["status"],
            "testcases_run": sorted(gate["testcases"]),
            "testcases_not_run": gate["excluded"],
        }
    log = REPO / f"verification/rtl/{name}/.klt/functional-verification/test_icarus.log"
    m = re.search(r"SUMMARY (.*)", log.read_text()) if log.exists() else None
    gate_provenance, gate_bullet = gate_level_bullets(gate, args.pdk_root, name)
    ctx = SimpleNamespace(args=args, sim=sim, syn=syn, prov=prov, versions=versions,
                          klt_provenance=klt_provenance_bullet(prov, versions), extra=extra,
                          gate=gate, gate_provenance=gate_provenance, gate_level=gate_bullet,
                          summary=m.group(1).strip() if m else "see sim.json")
    tail = f"- **Timestamp / author**: {{timestamp}}, {author}.\n"
    write_record(experiment, rev, inputs, meta_extra, body(ctx) + tail, generator)
    return 0
