"""The key-ladder formal record reads each run's depth from sby, not from a knob.

Issue #165: the Depth column of verification/records/keyladder-formal/ used to be
filled from four CLI arguments and three literals kept in step by hand with the
`.sby` files. Three P-6 rows were already mislabelled whenever the documented
`PROVE_DEPTH` knob was set, because `p6.sby` fixes those depths itself. The column
now comes from the `config.sby` that SymbiYosys writes into each run's work
directory, so these tests pin that reader's contract.

The formal flow itself is local-only (PDK, pinned sby, z3, and bounded runs past the
CI budget -- see verification/README.md), so this is the only automated check the
depth handling gets. It exercises the reader and the verdict rule, not the solver.

Issue #211 hoisted the depth reader into flow/common/record_lib.py, and issues
#259/#262 did the same for the mode reader and the steps-checked scrape. The
depth/mode reader-contract cases used to run here against every handle --
record_lib and both generators' imports -- so a local copy re-introduced into
either generator failed them; that 3-handle parametrization was reversed by
the operator ruling of 2026-11-17 (attended `/fleet:decide` round
20261116-r15, slate s3, issue #263): the contract now lives once in
verification/test_record_lib.py, run against record_lib directly. What guards
against a re-introduced generator-local copy here is
test_both_generators_use_the_shared_readers: its identity assertions fail a
local `def sby_depth`/`sby_mode` even before its contract can drift. The
steps-checked scrape contract followed by the operator ruling of 2026-11-23
(attended `/fleet:decide` round 20261121-r19, issue #307): its last 3-handle
fixture is gone, each supported line format's winning case runs once against
record_lib in test_record_lib.py, and the identity assertions are what still
guard the generator wiring. This file keeps the generator's own behaviour
(the verdict rule, the depth column, the no-depth-knob pins).
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GENERATOR = "verification/formal/keyladder/make_record.py"
DRBG_GENERATOR = "verification/formal/make_record.py"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gen():
    return _load("keyladder_make_record", GENERATOR)


@pytest.fixture(scope="module")
def drbg():
    return _load("drbg_make_record", DRBG_GENERATOR)


def test_both_generators_use_the_shared_readers(gen, drbg):
    """One parser per reader, not three: a generator-local `def sby_depth`
    would let the keyladder and DRBG/TRNG record families state different
    depths again (#211), and the same holds for the mode reader and the
    steps-checked scrape (#262). These identity assertions are the guard the
    operator rulings settled on (2026-11-17, round 20261116-r15, slate s3,
    issue #263; 2026-11-23, round 20261121-r19, issue #307 for the
    steps-checked scrape), after this file's reader-contract cases moved to
    verification/test_record_lib.py: they fail a re-introduced local copy
    even before its contract drifts -- the contract itself is pinned once,
    against record_lib, in test_record_lib.py."""
    shared = sys.modules["record_lib"]
    assert gen.sby_depth is shared.sby_depth
    assert drbg.sby_depth is shared.sby_depth
    assert drbg.sby_mode is shared.sby_mode
    # The keyladder generator binds no sby_mode by design -- its judge refuses
    # any run that names no depth whatever the mode (issue #224), so it never
    # states one; a module-level def beside the shared sby_depth would be a
    # shadow of a reader this generator must not state.
    assert not hasattr(gen, "sby_mode")
    assert gen.sby_steps_checked is shared.sby_steps_checked
    assert drbg.rc.sby_steps_checked is shared.sby_steps_checked
    # The DRBG/TRNG generator binds the scrape only through its `rc` import
    # (its steps_checked() wrapper calls rc.sby_steps_checked); a module-level
    # def re-introduced beside it would be an unused shadow of the one parser.
    assert not hasattr(drbg, "sby_steps_checked")


def test_collect_reports_the_configured_depth_of_a_finished_run(gen, tmp_path):
    d = tmp_path / "p6_rtl"
    d.mkdir()
    (d / "config.sby").write_text("[options]\nmode prove\ndepth 16\n")
    (d / "status").write_text("PASS\n")
    (d / "logfile.txt").write_text(
        "##   Checking assertions in step 0..\n"
        "##   Trying induction in step 15..\n##   Temporal induction successful.\n"
        "## Elapsed clock time [H:MM:SS (secs)]: 0:00:03 (3)\n")
    res = gen.collect(tmp_path, "p6", "rtl")
    # 16 is p6.sby's own hardcoded RTL depth. Before #165 this row was labelled with
    # PROVE_DEPTH, which p6.sby never reads -- so PROVE_DEPTH=8 recorded "8" here.
    assert res["depth"] == 16
    assert res["status"] == "PASS"


def test_a_finished_run_without_a_depth_fails_the_verdict(gen):
    """Rather than record a guess: the record is append-only, so a wrong depth
    cannot be corrected afterwards, only superseded."""
    res = {"sby": "p6", "task": "rtl", "status": "PASS", "depth": None, "trace": False}
    ok, why = gen.judge(res)
    assert not ok
    assert "no depth" in why


def test_a_finished_run_with_a_depth_is_judged_on_its_status(gen):
    assert gen.judge({"sby": "p6", "task": "rtl", "status": "PASS",
                      "depth": 16, "trace": False})[0]
    assert gen.judge({"sby": "p6", "task": "neg_rtl", "status": "FAIL",
                      "depth": 16, "trace": True})[0]


def test_a_missing_run_still_reports_its_status_not_its_depth(gen, tmp_path):
    """A run that never produced a status is MISSING; the depth rule must not mask it."""
    res = gen.collect(tmp_path, "p5", "rtl")
    assert res["status"] == "MISSING"
    ok, why = gen.judge(res)
    assert not ok
    assert "MISSING" in why


@pytest.mark.parametrize("arg", ["--prove-depth", "--p6-net-depth",
                                 "--p1-depth-rtl", "--p1-depth-net"])
def test_the_generator_takes_no_depth_arguments(tmp_path, arg):
    """The four hand-passed depths are gone, so no caller can label a row by hand."""
    out = subprocess.run([sys.executable, str(REPO / GENERATOR),
                          "--stage", str(tmp_path), "--pdk-root", str(tmp_path),
                          "--check-only", arg, "8"],
                         capture_output=True, text=True)
    assert out.returncode == 2
    assert "unrecognized arguments" in out.stderr


def _p5_options_depth_lines() -> dict[str, str]:
    """p5.sby's `[options]` depth assignments, as task -> value ("": un-prefixed)."""
    text = (REPO / "verification/formal/keyladder/p5.sby").read_text()
    depths: dict[str, str] = {}
    in_options = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_options = stripped == "[options]"
            continue
        if not in_options or not stripped or stripped.startswith("#"):
            continue
        m = re.match(r"^(?:(\w+):\s*)?depth\s+(\S+)$", stripped)
        if m:
            depths[m.group(1) or ""] = m.group(2)
    return depths


def test_p5_prove_depth_knob_reaches_the_proofs_never_the_controls():
    """Issue #210: an un-prefixed `[options] depth @DEPTH@` reached all four P-5
    tasks, so PROVE_DEPTH < 9 stopped the negative controls' BMC base case before
    their step-9 counterexample: sby returned UNKNOWN, judge() rejected the run
    ("expected FAIL with a counterexample trace") and no record was written -- a
    red flow indistinguishable from a real property defect. The knob must set the
    two proofs only; each must-fail control keeps a fixed depth of at least 9
    (counterexample at step 9; records 20261027-065038-a7475f5 and
    20261030-070100-8e25d3d, verified 2026-11-15).
    """
    depths = _p5_options_depth_lines()
    assert "" not in depths, (
        "p5.sby [options] carries an un-prefixed depth: it applies to every "
        "task, including the must-fail controls (issue #210)")
    assert set(depths) == {"rtl", "net", "neg_rtl", "neg_net"}, (
        f"every P-5 task must state its own depth, got {sorted(depths)}")
    assert depths["rtl"] == "@DEPTH@" and depths["net"] == "@DEPTH@", (
        "PROVE_DEPTH (@DEPTH@) must set the two P-5 proof depths")
    for task in ("neg_rtl", "neg_net"):
        value = depths[task]
        assert "@" not in value, (
            f"p5 {task} must not carry a knob placeholder: a low PROVE_DEPTH "
            "would stop its BMC before the step-9 counterexample (issue #210)")
        assert value.isdigit() and int(value) >= 9, (
            f"p5 {task} depth {value!r} < 9: the KL_NEG_MASK counterexample sits "
            "at step 9, so the control would end UNKNOWN (issue #210)")
