"""The drbg-trng formal EXPECT judge is tested, like its key-ladder sibling.

Issue #226: PR #220 made verification/formal/make_record.py's EXPECT table the
sole judge of every verification/formal/run.sh invocation (--check-only is
called unconditionally), so a silent regression there could weaken PASS / FAIL
/ PASS_OR_DEPTH into "records anyway". This pins the verdict:

- a row that meets its expectation is clean (all three expectation kinds),
- a FAIL control that timed out refuses the run,
- `net_bmc` is a plain-PASS row: a TIMEOUT there refuses the run (the
  distinction a mode-keyed "netlist proofs are depth-tolerant" fix loses),
- a PASS_OR_DEPTH netlist proof that stopped at its depth -- or left no depth
  at all -- is clean,
- an unknown (file, task) row refuses, and
- --check-only writes nothing, whatever the verdict.

The verdict loop is inline in the generator's main() (the sibling has judge()
factored out; this one does not, and is not refactored for this test), so the
verdict fixtures drive the generator as a subprocess over synthetic out-dirs
-- the plain files run.sh leaves behind: a results.tsv (7 tab-separated
fields, `base` keeping its .sby suffix) plus per-task work directories named
{base-without-.sby}_{task}. Assertions are on the generator's own exit code
and stderr, never on a re-implementation of the rule. The module is imported
(importlib, as in the sibling test) only for the sby_depth() /
steps_checked() readers and its real EXPECT table, which the fixtures anchor
to and never re-declare.

The formal flow itself is local-only (PDK, pinned sby, bounded runs past the
CI budget -- see verification/README.md), so this is the only automated check
the judge gets.
"""

from __future__ import annotations

import hashlib
import importlib.util
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


def _out_dir(tmp_path: Path, rows: list[str]) -> Path:
    d = tmp_path / "formal-out"
    d.mkdir()
    (d / "results.tsv").write_text("".join(row + "\n" for row in rows))
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
    _workdir(out, "net_p7_p8.sby", "net_prove")
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
    work. Tripwire: dirty one of the generator's declared INPUTS.
    require_clean_inputs() refuses any run in that state (SystemExit, "an
    input is modified"), so an exit 0 here proves the verdict path never
    reached it -- recording from a synthetic out-dir cannot happen."""
    spec_md = REPO / "spec" / "key-isolation-properties.md"
    original = spec_md.read_bytes()
    spec_md.write_bytes(original + b"\n<!-- issue #226 check-only tripwire -->\n")
    try:
        out = _out_dir(tmp_path, [_row("p9.sby", "bmc", "PASS")])
        r = _check(out)
        assert r.returncode == 0
        assert "an input is modified" not in r.stderr
    finally:
        spec_md.write_bytes(original)


# ---- the readers the verdict (and the Depth column) lean on ----------------


def test_sby_depth_reads_the_options_section(gen, tmp_path):
    d = tmp_path / "net_p9_net_prove"
    d.mkdir()
    (d / "config.sby").write_text(
        "[options]\nmode prove\ndepth 20\n\n[engines]\nabc pdr\n\n[script]\nprep -top top\n")
    assert gen.sby_depth(d) == 20


def test_sby_depth_ignores_depth_outside_options(gen, tmp_path):
    """A `depth` word in [script] (e.g. a define) is not the run's depth."""
    d = tmp_path / "t"
    d.mkdir()
    (d / "config.sby").write_text(
        "[options]\nmode bmc\n\n[script]\nread_verilog -Ddepth 99 dut.v\n")
    assert gen.sby_depth(d) is None


def test_sby_depth_missing_config_or_depth_is_never_a_guess(gen, tmp_path):
    """sby defaults depth to 20; a record must state what ran, so an absent
    config or an [options] without a depth line reads None, never 20."""
    d = tmp_path / "t"
    d.mkdir()
    assert gen.sby_depth(d) is None
    (d / "config.sby").write_text("[options]\nmode bmc\ntimeout 1500\n")
    assert gen.sby_depth(d) is None


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
