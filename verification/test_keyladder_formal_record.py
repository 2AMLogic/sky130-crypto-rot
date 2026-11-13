"""The key-ladder formal record reads each run's depth from sby, not from a knob.

Issue #165: the Depth column of verification/records/keyladder-formal/ used to be
filled from four CLI arguments and three literals kept in step by hand with the
`.sby` files. Three P-6 rows were already mislabelled whenever the documented
`PROVE_DEPTH` knob was set, because `p6.sby` fixes those depths itself. The column
now comes from the `config.sby` that SymbiYosys writes into each run's work
directory, so these tests pin that reader's contract.

The formal flow itself is local-only (PDK, pinned sby, z3, and bounded runs past the
CI budget -- see verification/README.md), so this is the only automated check the
generator's depth handling gets. It exercises the reader and the verdict rule, not
the solver.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GENERATOR = "verification/formal/keyladder/make_record.py"

# A real config.sby, byte-for-byte as the pinned yowasp-yosys wheel
# (YOWASP_YOSYS_VERSION in scripts/setup-env.sh) wrote it for a two-task file whose
# `[options]` read `mode bmc` / `a: depth 5` / `b: depth 7`. Captured from the tool
# rather than hand-written, so a format change in a re-pinned sby breaks this test
# instead of silently changing a record's Depth column.
REAL_CONFIG_SBY = """[options]
mode bmc
depth 5

[engines]
smtbmc z3

[script]
read_verilog -formal tiny.v
prep -flatten -top tiny

[files]
tiny.v
"""


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("keyladder_make_record", REPO / GENERATOR)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["keyladder_make_record"] = mod
    spec.loader.exec_module(mod)
    return mod


def _workdir(tmp_path: Path, config: str | None) -> Path:
    d = tmp_path / "p6_rtl"
    d.mkdir()
    if config is not None:
        (d / "config.sby").write_text(config)
    return d


def test_reads_the_depth_from_a_real_config_sby(gen, tmp_path):
    assert gen.sby_depth(_workdir(tmp_path, REAL_CONFIG_SBY)) == 5


def test_task_prefixes_are_already_resolved_by_sby(gen, tmp_path):
    """sby writes the depth of THIS task, so the reader never resolves `net:` itself."""
    assert gen.sby_depth(_workdir(tmp_path, "[options]\nmode prove\ndepth 2\n")) == 2


def test_trailing_comment_on_the_depth_line(gen, tmp_path):
    """sby strips a trailing ` #...` from an [options] line; so does the reader."""
    assert gen.sby_depth(_workdir(tmp_path, "[options]\nmode bmc\ndepth 24  # bounded\n")) == 24


def test_comment_and_blank_lines_inside_options(gen, tmp_path):
    cfg = "[options]\n# the knob below is p6.sby's own\n\nmode prove\ndepth 16\n"
    assert gen.sby_depth(_workdir(tmp_path, cfg)) == 16


def test_depth_outside_the_options_section_is_ignored(gen, tmp_path):
    """Only `[options]` configures the run; a `depth` word elsewhere is not a depth."""
    cfg = ("[options]\nmode bmc\ndepth 32\n\n[script]\n"
           "read_verilog -formal -Ddepth 99 dut.v\nprep -top keyladder\n")
    assert gen.sby_depth(_workdir(tmp_path, cfg)) == 32


def test_last_assignment_wins(gen, tmp_path):
    """sby's [options] reader is a dict assignment, so a later line overrides."""
    assert gen.sby_depth(_workdir(tmp_path, "[options]\ndepth 8\ndepth 16\n")) == 16


def test_missing_config_sby_is_not_a_depth(gen, tmp_path):
    assert gen.sby_depth(_workdir(tmp_path, None)) is None


def test_options_without_a_depth_does_not_assume_sbys_default(gen, tmp_path):
    """sby defaults depth to 20. A record must state what ran, so None, never 20."""
    assert gen.sby_depth(_workdir(tmp_path, "[options]\nmode bmc\ntimeout 1500\n")) is None


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
