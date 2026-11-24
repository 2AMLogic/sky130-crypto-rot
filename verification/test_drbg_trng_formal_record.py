"""The drbg-trng formal record's EXPECT judge and mode-aware Depth rule.

One generator (verification/formal/make_record.py), one record, one test
module -- two postures over its two contracts, kept together rather than in
parallel files (issue #322; the split was parallel-issue drift, not design).

Issue #226: PR #220 made the generator's EXPECT table the sole judge of every
verification/formal/run.sh invocation (--check-only is called
unconditionally), so a silent regression there could weaken PASS / FAIL
/ PASS_OR_DEPTH into "records anyway". This pins the verdict:

- a row that meets its expectation is clean (all three expectation kinds),
- a FAIL control that timed out refuses the run,
- `net_bmc` is a plain-PASS row: a TIMEOUT there refuses the run (the
  distinction a mode-keyed "netlist proofs are depth-tolerant" fix loses),
- a PASS_OR_DEPTH netlist proof that stopped at its depth -- or left no depth
  at all -- is clean,
- an unknown (file, task) row refuses, and
- --check-only writes nothing, whatever the verdict.

Issue #224: `sby_depth` collapses "no `config.sby` at all" (sby never wrote
one -- a genuinely broken run) and "a `config.sby` with no `depth` line" (an
unbounded `mode prove` task -- p7_p8.sby/prove and p9.sby/prove, the record's
primary claim) into one None. The rule is mode-aware, read from the same
resolved config.sby the depth comes from (issue #165): a run with no
config.sby refuses to record, a bounded (`mode bmc`/`mode cover`) task
without a depth refuses to record, and a depth-less `mode prove` task is the
unbounded proof and records as `unbounded` -- never None -- with the
net_prove shape (prove + depth) recording that depth unchanged. The keyladder
generator keeps its own blanket guard (every keyladder task names a depth,
including its prove ones) and is deliberately not aligned with this one
(issue #224, out of scope).

The two postures share the fixtures but drive the generator differently,
each the only honest way to its subject. The verdict loop is inline in the
generator's main() (the sibling has judge() factored out; this one does not,
and is not refactored for this test), so the verdict fixtures drive the
generator as a subprocess over synthetic out-dirs -- the plain files run.sh
leaves behind: a results.tsv (7 tab-separated fields, `base` keeping its
.sby suffix) plus per-task work directories named {base-without-.sby}_{task};
assertions are on the generator's own exit code and stderr, never on a
re-implementation of the rule. The Depth-rule and record-wording tests
instead import the module (importlib, as in the sibling test) and stub the
record-path plumbing (clean-tree check, tool-version probes): the verdict
rule and the Depth cell are under test there, not git or the tools, and the
stub doubles as the spy pinning that a refused run touches none of it. The
module import also reaches the steps_checked() reader and the real EXPECT
table, which the fixtures anchor to and never re-declare; the config.sby
reader contract lives in test_record_lib.py (issues #259, #262, #263), and
the identity assertions in test_keyladder_formal_record.py pin this
generator's import of it.

The formal flow itself is local-only (PDK, pinned sby, bounded runs past the
CI budget -- see verification/README.md), so this is the only automated
check the generator's verdict rule and its Depth rule get. The tests
exercise the verdict and the Depth-cell rendering, not the solver.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GENERATOR = "verification/formal/make_record.py"
RECORDS_DIR = REPO / "verification/records/drbg-trng-formal"


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("drbg_trng_make_record", REPO / GENERATOR)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["drbg_trng_make_record"] = mod
    spec.loader.exec_module(mod)
    return mod


def _row(base: str, task: str, status: str, rc: str = "0") -> str:
    """One results.tsv line, exactly run.sh's printf: 7 tab-separated fields,
    `base` keeping its .sby suffix. sby exits non-zero on a status its `expect`
    line did not ask for, so TIMEOUT rows carry rc != 0 (which the judge
    deliberately ignores for a PASS_OR_DEPTH row's inconclusive branch)."""
    return f"{base}\t{task}\t{status}\t{rc}\tengine_0 (abc pdr) returned {status}\t-\t1"


def _out_dir(tmp_path: Path, rows: list[str], *,
             configs: dict[tuple[str, str], str | None] | None = None) -> Path:
    """A synthetic out dir: results.tsv plus the per-task work directories,
    each carrying the config.sby sby would have resolved (or none). With no
    `configs` mapping every row gets the default a healthy run leaves: a
    depth-less `mode prove` for a proof task, a bounded bmc otherwise (issue
    #224's guard needs one either way). With a mapping, each row gets exactly
    the config it names -- `None` meaning the work directory exists but sby
    wrote no config.sby; tests that care can still overwrite via
    _workdir(config=...)."""
    d = tmp_path / "formal-out"
    d.mkdir()
    (d / "results.tsv").write_text("".join(row + "\n" for row in rows))
    for row in rows:
        base, task = row.split("\t")[:2]
        cfg = configs[(base, task)] if configs is not None else (
            "[options]\nmode prove\n" if task.endswith("prove")
            else "[options]\nmode bmc\ndepth 20\n")
        _workdir(d, base, task, config=cfg)
    return d


def _workdir(out_dir: Path, base: str, task: str, *,
             config: str | None = None, logfile: str | None = None) -> Path:
    """The per-task work directory sby leaves: {base-without-.sby}_{task}."""
    d = out_dir / f"{base[:-4]}_{task}"
    d.mkdir(parents=True, exist_ok=True)
    if config is not None:
        (d / "config.sby").write_text(config)
    if logfile is not None:
        (d / "logfile.txt").write_text(logfile)
    return d


def _check(out_dir: Path):
    return subprocess.run(
        [sys.executable, str(REPO / GENERATOR), "--out-dir", str(out_dir), "--check-only"],
        capture_output=True, text=True)


@pytest.fixture
def no_record_written():
    """--check-only must write nothing for any verdict: the experiment's
    records directory comes back byte-identical (nothing added, removed or
    edited), so a future change that starts recording under --check-only
    fails here instead of silently appending to the record chain."""
    def snapshot():
        if not RECORDS_DIR.is_dir():
            return []
        return sorted(
            (str(p.relative_to(RECORDS_DIR)), hashlib.sha256(p.read_bytes()).hexdigest())
            for p in RECORDS_DIR.rglob("*") if p.is_file())
    before = snapshot()
    yield
    assert snapshot() == before


# ---- the verdict, over the real EXPECT table -------------------------------


def test_all_healthy_run_is_clean(gen, tmp_path, no_record_written):
    """One healthy row of each expectation kind, picked from the real table:
    a PASS proof, a FAIL vacuity/negative control that failed, and a
    PASS_OR_DEPTH netlist proof that passed outright."""
    kinds: dict[str, tuple[str, str]] = {}
    for (f, t), (kind, _why) in gen.EXPECT.items():
        kinds.setdefault(kind, (f, t))
    assert set(kinds) == {"PASS", "FAIL", "PASS_OR_DEPTH"}
    rows = [_row(f, t, "FAIL" if kind == "FAIL" else "PASS")
            for kind, (f, t) in sorted(kinds.items())]
    out = _out_dir(tmp_path, rows)
    r = _check(out)
    assert r.returncode == 0
    assert r.stderr == ""


def test_fail_control_that_times_out_refuses_the_run(gen, tmp_path, no_record_written):
    """`net_neg_interval` expects FAIL (the mutant must be caught); a TIMEOUT
    is not a failure of the mutant, so the run is not judged clean."""
    out = _out_dir(tmp_path, [_row("net_p7_p8.sby", "net_neg_interval", "TIMEOUT", rc="1")])
    r = _check(out)
    assert r.returncode == 1
    assert "a task did not meet its expectation" in r.stderr
    assert "net_p7_p8.sby net_neg_interval: expected FAIL" in r.stderr


def test_net_bmc_timeout_refuses_the_run(gen, tmp_path, no_record_written):
    """The load-bearing row: `net_bmc` is plain PASS, not PASS_OR_DEPTH -- the
    bounded netlist check must actually pass, and a mode-keyed "netlist proofs
    are depth-tolerant" fix that waves a TIMEOUT through here is a defect."""
    assert gen.EXPECT[("net_p9.sby", "net_bmc")][0] == "PASS"
    out = _out_dir(tmp_path, [_row("net_p9.sby", "net_bmc", "TIMEOUT", rc="1")])
    r = _check(out)
    assert r.returncode == 1
    assert "net_p9.sby net_bmc: expected PASS, got status TIMEOUT" in r.stderr


def test_netlist_proof_timeout_with_depth_is_clean(gen, tmp_path, no_record_written):
    """A PASS_OR_DEPTH netlist proof may stop inconclusively at its depth or
    the per-task cap: the run is judged clean, and the logfile's last checked
    step is what the record would state (run.sh passes --check-only first, so
    nothing is written either way)."""
    out = _out_dir(tmp_path, [_row("net_p9.sby", "net_prove", "TIMEOUT", rc="1")])
    _workdir(out, "net_p9.sby", "net_prove",
             config="[options]\nmode prove\ndepth 20\n",
             logfile="##   Checking assertions in step 0..\n"
                     "##   Checking assertions in step 14..\n")
    r = _check(out)
    assert r.returncode == 0
    assert r.stderr == ""


def test_netlist_proof_timeout_without_a_depth_is_still_clean(gen, tmp_path, no_record_written):
    """PASS_OR_DEPTH accepts an inconclusive stop even when the engine left no
    depth at all (no logfile.txt): recorded as not proven, no depth reached --
    never guessed from sby's own default."""
    out = _out_dir(tmp_path, [_row("net_p7_p8.sby", "net_prove", "UNKNOWN", rc="1")])
    _workdir(out, "net_p7_p8.sby", "net_prove", config="[options]\nmode prove\n")
    r = _check(out)
    assert r.returncode == 0
    assert r.stderr == ""


def test_unknown_task_row_refuses_the_run(gen, tmp_path, no_record_written):
    """A row whose (file, task) pair the table does not name refuses the run --
    e.g. this pairing, real task, wrong sby file: how a hand-edited task list
    would drift."""
    assert ("net_p9.sby", "net_reach_over") not in gen.EXPECT
    out = _out_dir(tmp_path, [_row("net_p9.sby", "net_reach_over", "FAIL")])
    r = _check(out)
    assert r.returncode == 1
    assert "unexpected task row net_p9.sby net_reach_over" in r.stderr


def test_empty_results_tsv_refuses_the_run(gen, tmp_path, no_record_written):
    """No task results (sby died before the first task) is not a clean run."""
    out = _out_dir(tmp_path, [])
    r = _check(out)
    assert r.returncode == 1
    assert "no task results found" in r.stderr


def test_the_fixtures_anchor_to_the_real_expect_table(gen):
    """The verdict fixtures above hardcode row names; this ties them to the
    committed table (never re-declared in this test). Exactly two rows are
    depth-tolerant, both netlist `net_prove` proofs -- the count a naive
    "three proof tasks" fix would get wrong."""
    e = gen.EXPECT
    assert e[("net_p7_p8.sby", "net_neg_interval")][0] == "FAIL"
    assert e[("net_p9.sby", "net_prove")][0] == "PASS_OR_DEPTH"
    assert sorted(k for k, v in e.items() if v[0] == "PASS_OR_DEPTH") == [
        ("net_p7_p8.sby", "net_prove"),
        ("net_p9.sby", "net_prove"),
    ]


# ---- --check-only never does record work -----------------------------------


def test_check_only_never_reaches_require_clean_inputs(gen, tmp_path):
    """--check-only returns right after the verdict, before any recording
    work. Tripwire: an untracked stray dropped directly beside the
    generator -- require_clean_inputs() refuses any run in that state
    (SystemExit, "an input is modified"), so an exit 0 here proves the
    verdict path never reached it -- recording from a synthetic out-dir
    cannot happen. The stray lives in the generator's own directory, never
    in a tracked file: recovery is rm, not a git checkout of ratified
    spec content (issue #241)."""
    stray = REPO / "verification" / "formal" / f"issue241-tripwire-{os.getpid()}.tmp"
    stray.write_text("untracked stray; require_clean_inputs() refuses on one\n")
    try:
        out = _out_dir(tmp_path, [_row("p9.sby", "bmc", "PASS")])
        r = _check(out)
        assert r.returncode == 0
        assert "an input is modified" not in r.stderr
    finally:
        stray.unlink(missing_ok=True)


# ---- the logfile reader the verdict (and the reached-depth column) lean on --


def test_steps_checked_takes_the_last_checked_step(gen, tmp_path):
    d = tmp_path / "t"
    d.mkdir()
    (d / "logfile.txt").write_text(
        "##   Checking assumptions and assertions in step 0..\n"
        "##   Checking assertions in step 14..\n"
        "##   Checking assertions in step 7..\n")
    assert gen.steps_checked(d) == 14


def test_steps_checked_without_a_log_or_steps_is_none(gen, tmp_path):
    """logfile.txt is missing when sby dies early; a log without checking
    lines says nothing either -- both read None, not zero."""
    d = tmp_path / "t"
    d.mkdir()
    assert gen.steps_checked(d) is None
    (d / "logfile.txt").write_text("engine killed before any step\n")
    assert gen.steps_checked(d) is None


# ---- the mode-aware Depth rule ----------------------------------------------
#
# These import the module and stub the record path (_run_gen +
# _stub_record_path): the Depth column and the record body are what is under
# test, and the stub is the spy that pins a refused run never reaches the
# record plumbing. The subprocess posture above stays the judge of the
# --check-only contract.

# A config.sby as the pinned sby writes it for a resolved single task: the
# `[tasks]` prefixes are already applied, so one `[options]` block states THIS
# task's mode and depth (the same reader contract the keyladder tests pin).
CONFIG = {
    "bmc30": "[options]\nmode bmc\ndepth 30\n\n[engines]\nabc bmc3\n",
    "cover_no_depth": "[options]\nmode cover\n\n[engines]\nabc bmc3\n",
    "bmc_no_depth": "[options]\nmode bmc\n\n[engines]\nabc bmc3\n",
    "prove_unbounded": "[options]\nmode prove\n\n[engines]\nabc pdr\n",
    "prove20": "[options]\nmode prove\ndepth 20\n\n[engines]\nabc pdr\n",
    "no_mode": "[options]\ndepth 30\n\n[engines]\nabc pdr\n",
}


def _stub_record_path(monkeypatch, gen):
    """Stub the post-verdict record plumbing on the loaded module's rc: the
    verdict rule and the Depth cell are under test here, not git or the tools.
    Returns the spy so tests can pin that a refused run touches none of it."""
    calls = {"require_clean_inputs": 0, "write_record": []}

    def _require(*_a, **_k):
        calls["require_clean_inputs"] += 1
        return "0123456789abcdef"

    def _write(experiment, rev, inputs, meta, body, generator=None):
        calls["write_record"].append((experiment, rev, body))

    monkeypatch.setattr(gen.rc, "require_clean_inputs", _require)
    monkeypatch.setattr(
        gen.rc, "tool_versions",
        lambda: {"yowasp_yosys": "0.44.2", "yosys_wasm": "1.153",
                 "python": "3.11.8", "klt_pin": "v0.0-test"})
    monkeypatch.setattr(gen.rc, "run", lambda *_a, **_k: "sby (stubbed)")
    monkeypatch.setattr(gen.rc, "write_record", _write)
    return calls


def _run_gen(gen, out_dir, monkeypatch, check_only=True):
    argv = ["make_record.py", "--out-dir", str(out_dir)]
    if check_only:
        argv.append("--check-only")
    monkeypatch.setattr(sys, "argv", argv)
    return gen.main()


# --- the sby_mode reader contract: pinned in test_record_lib.py (issue #263), -
# --- with the identity of this generator's import pinned by the keyladder -----
# --- file's test_both_generators_use_the_shared_readers. The premise test ----
# --- below stays: it is the verdict rule's, not a reader contract. -----------


def test_depthless_prove_run_is_distinguishable_from_a_broken_one(gen, tmp_path):
    """The issue #224 premise: sby_depth alone collapses the two None cases;
    sby_mode tells them apart."""
    broken = tmp_path / "broken"
    broken.mkdir()
    unbounded = tmp_path / "p7_p8_prove"
    unbounded.mkdir()
    (unbounded / "config.sby").write_text(CONFIG["prove_unbounded"])
    assert gen.sby_mode(broken) is None and gen.sby_depth(broken) is None
    assert gen.sby_mode(unbounded) == "prove" and gen.sby_depth(unbounded) is None


# --- the verdict rule: refuse broken, refuse bounded-without-depth, -----------
# --- record the unbounded proof ----------------------------------------------


def test_bmc_with_depth_records_with_that_depth(gen, monkeypatch, tmp_path):
    out = _out_dir(tmp_path, [_row("p9.sby", "bmc", "PASS")],
                   configs={("p9.sby", "bmc"): CONFIG["bmc30"]})
    calls = _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch, check_only=False) == 0
    (experiment, _rev, body) = calls["write_record"][0]
    assert experiment == gen.EXPERIMENT
    assert "| `p9.sby` | `bmc` | PASS | engine_0 (abc pdr) returned PASS | 30 |" in body


def test_bmc_without_a_depth_refuses_to_record(gen, monkeypatch, capsys, tmp_path):
    """A bounded task must state the depth it ran at: a passing run with no
    depth still refuses, because the record is append-only (issue #224). The
    refusal names why: the task's config.sby states no depth."""
    out = _out_dir(tmp_path, [_row("p9.sby", "bmc", "PASS")],
                   configs={("p9.sby", "bmc"): CONFIG["bmc_no_depth"]})
    calls = _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch) == 1
    assert calls["require_clean_inputs"] == 0
    assert calls["write_record"] == []
    err = capsys.readouterr().err
    assert "names no depth" in err
    assert "p9.sby bmc" in err


def test_cover_without_a_depth_refuses_to_record(gen, monkeypatch, tmp_path):
    out = _out_dir(tmp_path, [_row("p9.sby", "bmc", "PASS")],
                   configs={("p9.sby", "bmc"): CONFIG["cover_no_depth"]})
    calls = _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch) == 1
    assert calls["require_clean_inputs"] == 0
    assert calls["write_record"] == []


@pytest.mark.parametrize("sby,task", [("p7_p8.sby", "prove"), ("p9.sby", "prove")])
def test_depthless_prove_run_records_unbounded(gen, monkeypatch, tmp_path, sby, task):
    """The regression guard for the record's two real rows: P-7/P-8 and P-9 are
    unbounded `abc pdr` proofs with no depth line by design. They must keep
    recording, with the Depth cell reading `unbounded`, not None."""
    out = _out_dir(tmp_path, [_row(sby, task, "PASS")],
                   configs={(sby, task): CONFIG["prove_unbounded"]})
    calls = _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch, check_only=False) == 0
    (_experiment, _rev, body) = calls["write_record"][0]
    assert f"| `{sby}` | `{task}` | PASS | engine_0 (abc pdr) returned PASS | unbounded |" in body
    assert "| None |" not in body


def test_prove_with_a_depth_records_it_unchanged(gen, monkeypatch, tmp_path):
    """The net_prove shape: mode prove AND a depth (resolved from
    @NET_PROVE_DEPTH@) records that depth, not `unbounded`."""
    out = _out_dir(tmp_path, [_row("net_p9.sby", "net_prove", "PASS")],
                   configs={("net_p9.sby", "net_prove"): CONFIG["prove20"]})
    calls = _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch, check_only=False) == 0
    (_experiment, _rev, body) = calls["write_record"][0]
    assert "| `net_p9.sby` | `net_prove` | PASS | engine_0 (abc pdr) returned PASS | 20 |" in body


def test_inconclusive_net_prove_at_its_depth_still_records(gen, monkeypatch, tmp_path):
    """The PASS_OR_DEPTH rows may end TIMEOUT/UNKNOWN at their depth and are
    recorded as not proven (issue #177): the mode-aware guard must keep that
    path open -- a prove task that names a depth is never the broken case."""
    out = _out_dir(tmp_path, [_row("net_p9.sby", "net_prove", "TIMEOUT")],
                   configs={("net_p9.sby", "net_prove"): CONFIG["prove20"]})
    _workdir(out, "net_p9.sby", "net_prove",
             logfile="##   Checking assertions in step 0..\n"
                     "##   Trying induction in step 19..\n"
                     "##   Checking assertions in step 14..\n"
                     "## Status for engine_0: TIMEOUT\n")
    calls = _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch, check_only=False) == 0
    (_experiment, _rev, body) = calls["write_record"][0]
    assert "TIMEOUT -- reached depth 14, not proven" in body
    assert ("| `net_p9.sby` | `net_prove` | TIMEOUT -- reached depth 14, not proven"
            " | engine_0 (abc pdr) returned TIMEOUT | 20 |") in body


def test_record_wording_keeps_the_notes_drops_the_closed_gap(gen, monkeypatch, tmp_path):
    """Issue #129: a newly rendered record states the configured engines and
    `aigsmt none`, keeps the still-active short-TMPDIR synthesis note, and no
    longer claims the venv's sby ships no SMT solver or needs a helper shim
    (setup-env.sh links sby and both helper names from the pinned wheel).
    Records are append-only: this pins the template's wording, not any
    published record, and mints no evidence from synthetic results."""
    out = _out_dir(tmp_path, [_row("p7_p8.sby", "prove", "PASS")],
                   configs={("p7_p8.sby", "prove"): CONFIG["prove_unbounded"]})
    calls = _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch, check_only=False) == 0
    body = calls["write_record"][0][2]
    assert "`abc pdr`" in body and "`abc bmc3`" in body
    assert "`aigsmt none`" in body
    assert "short `TMPDIR`" in body        # the netlist synthesis note stays
    assert "klayout-tools#5780" in body    # with its upstream reference
    assert "no SMT solver" not in body     # the closed gap is not re-asserted
    assert "formal-bin" not in body        # neither is the removed shim


def test_run_with_no_config_sby_refuses_to_record(gen, monkeypatch, capsys, tmp_path):
    """sby never wrote a config.sby: neither the mode nor the depth of what ran
    can be stated, so the run is broken and refuses (issue #224) -- and the
    refusal says that."""
    out = _out_dir(tmp_path, [_row("p9.sby", "bmc", "ERROR", rc="1")],
                   configs={("p9.sby", "bmc"): None})
    calls = _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch) == 1
    assert calls["require_clean_inputs"] == 0
    assert calls["write_record"] == []
    err = capsys.readouterr().err
    assert "no config.sby" in err


def test_modeless_config_refusal_names_the_case(gen, monkeypatch, capsys, tmp_path):
    """A config.sby that is present but names no `mode` under `[options]`
    refuses too, and the refusal must say THAT: not claim the file is missing
    (issue #243) -- sby_mode's two None meanings get two distinct messages."""
    out = _out_dir(tmp_path, [_row("p9.sby", "bmc", "PASS")],
                   configs={("p9.sby", "bmc"): CONFIG["no_mode"]})
    _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch) == 1
    err = capsys.readouterr().err
    assert "no config.sby" not in err      # the file exists; do not claim otherwise
    assert "no mode line" in err           # the refusal states the actual case
    assert "p9.sby bmc" in err


def test_a_task_that_met_its_expectation_still_needs_its_depth(gen, monkeypatch, capsys, tmp_path):
    """Pin the exact failing shape the guard exists for: a negative control met
    its expectation (expected FAIL, got FAIL) and STILL refuses, on the Depth
    column alone -- the refusal names the depth rule, not the expectation."""
    out = _out_dir(tmp_path, [_row("p7_p8.sby", "reach_valid", "FAIL")],
                   configs={("p7_p8.sby", "reach_valid"): CONFIG["bmc_no_depth"]})
    calls = _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch) == 1
    assert calls["require_clean_inputs"] == 0
    assert calls["write_record"] == []
    err = capsys.readouterr().err
    assert "expected FAIL" not in err          # the expectation was met
    assert "names no depth" in err             # the refusal is the Depth rule
