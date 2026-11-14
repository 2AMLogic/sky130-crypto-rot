"""Tests for the shared gate-level driver steps in flow/common/core_flow.sh.

The gate-level mode (issue #179) puts three refusals in the flow, and each one
exists because the failure it prevents would otherwise read as a PASS:

  * a stale netlist in a dirty flow/build/<core>/ would be simulated in place of
    this run's, so the record's netlist hash would name gates nobody ran;
  * a testcase in neither GATE_TESTCASES nor GATE_EXCLUDED would silently skip
    the gate-level run, which is exactly what AC5 forbids -- a check that reads
    an internal RTL signal name must either run at gate level or be named in
    the record as not run there;
  * --sim-only --gate-level cannot mean anything, since --sim-only is CI's path
    and never synthesizes the netlist --gate-level simulates.

They are tested here rather than left to the real runs because the real runs
take half an hour and are off CI's path, so nothing else would notice if a
refusal stopped refusing. The two Python snippets are extracted from the shell
file by name and run exactly as the shell runs them, so the test cannot drift
from the code: if the snippet is renamed, extraction fails rather than silently
testing nothing. Standard library plus pytest only.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CORE_FLOW = REPO / "flow/common/core_flow.sh"
TEXT = CORE_FLOW.read_text()

TEMPLATES = sorted((REPO / "verification/rtl").glob("*/sim-gate-request.json.in"))


def snippet(name: str) -> str:
    """The body of the single-quoted `<name>='...'` Python block in core_flow.sh."""
    m = re.search(rf"^{re.escape(name)}='\n(.*?)\n'\n", TEXT, re.S | re.M)
    assert m, f"{name} is not a single-quoted Python block in {CORE_FLOW}"
    return m.group(1)


def run_snippet(name: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", snippet(name), *args],
                          capture_output=True, text=True)


def core_config(core: str) -> tuple[str, str]:
    """(GATE_TESTCASES, GATE_EXCLUDED) exactly as that core's run.sh declares them."""
    text = (REPO / "verification/rtl" / core / "run.sh").read_text()
    def one(name: str) -> str:
        m = re.search(rf'^{name}="(.*)"$', text, re.M)
        return m.group(1) if m else ""
    return one("GATE_TESTCASES"), one("GATE_EXCLUDED")


# --- testcase coverage: AC5 as a gate ---------------------------------------

@pytest.mark.parametrize("core", ["aes", "sha256"])
def test_each_core_s_own_declaration_covers_its_whole_bench(core):
    """The shipped GATE_TESTCASES/GATE_EXCLUDED must already satisfy the check."""
    run, excluded = core_config(core)
    bench = REPO / "verification/rtl" / core / f"test_{core}_core.py"
    out = run_snippet("_GATE_COVERAGE_PY", str(bench), run, excluded)
    assert out.returncode == 0, out.stderr
    assert "gate-level testcase coverage: run" in out.stdout


def test_a_testcase_in_neither_list_refuses_the_run():
    bench = REPO / "verification/rtl/sha256/test_sha256_core.py"
    out = run_snippet("_GATE_COVERAGE_PY", str(bench), "test_scrub", "")
    assert out.returncode != 0
    assert "test_sha256_core" in out.stderr and "test_million_a" in out.stderr
    assert "AC5" in out.stderr


def test_an_exclusion_without_a_reason_refuses_the_run():
    """"Not run at gate level" is only honest in the record if it says why."""
    bench = REPO / "verification/rtl/sha256/test_sha256_core.py"
    out = run_snippet("_GATE_COVERAGE_PY", str(bench),
                      "test_scrub test_sha256_core", "test_million_a=")
    assert out.returncode != 0 and "no reason" in out.stderr
    out = run_snippet("_GATE_COVERAGE_PY", str(bench),
                      "test_scrub test_sha256_core", "test_million_a")
    assert out.returncode != 0 and "<name>=<reason>" in out.stderr


def test_a_name_that_is_not_a_testcase_refuses_the_run():
    """A renamed testcase must not leave a declaration silently matching nothing."""
    bench = REPO / "verification/rtl/aes/test_aes_core.py"
    out = run_snippet("_GATE_COVERAGE_PY", str(bench), "test_aes_core test_typo", "")
    assert out.returncode != 0 and "no testcase" in out.stderr and "test_typo" in out.stderr


def test_a_name_both_run_and_excluded_refuses_the_run():
    bench = REPO / "verification/rtl/aes/test_aes_core.py"
    out = run_snippet("_GATE_COVERAGE_PY", str(bench), "test_aes_core",
                      "test_aes_core=cannot be both")
    assert out.returncode != 0 and "both run and excluded" in out.stderr


# --- request rendering: the netlist is read, and verified ---------------------

def _synth_report(tmp_path, netlist: Path, sha: str | None = None) -> Path:
    report = tmp_path / "synth.json"
    report.write_text(json.dumps({
        "status": "ok",
        "instance_count": 7,
        "netlist_path": {"path": str(netlist), "scope": "repo"},
        "netlist_sha256": sha or hashlib.sha256(netlist.read_bytes()).hexdigest(),
    }))
    return report


def _render(tmp_path, report: Path, template: Path, testcase="test_aes_core"):
    models = tmp_path / "models"
    models.mkdir(exist_ok=True)
    for name in ("primitives.v", "sky130_fd_sc_hd.v"):
        (models / name).write_text("// model\n")
    out = tmp_path / "gate" / "request.json"
    return run_snippet("_GATE_RENDER_PY", str(template), str(report), str(out),
                       testcase, str(tmp_path), str(models), str(REPO)), out


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.parent.name)
def test_render_substitutes_every_placeholder_and_drops_the_comment(tmp_path, template):
    netlist = tmp_path / "core_synth.v"
    netlist.write_text("module m; endmodule\n")
    testcase = json.loads(re.sub(r"@[A-Z_]+@", "x", template.read_text()))["testbench"]["module"]
    done, out = _render(tmp_path, _synth_report(tmp_path, netlist), template, testcase)
    assert done.returncode == 0, done.stderr
    req = json.loads(out.read_text())
    assert not re.search(r"@[A-Z_]+@", out.read_text())
    assert "_comment" not in req, "the rendered request is the shape klt gets"
    assert req["sources"][-1] == str(netlist), "cell models first, netlist last"
    assert [Path(p).name for p in req["sources"][:2]] == ["primitives.v",
                                                         "sky130_fd_sc_hd.v"]
    assert req["options"]["defines"] == {"FUNCTIONAL": None, "UNIT_DELAY": "#1"}
    assert "sdf" not in req["options"], "pre-layout: there is nothing to annotate"
    assert req["testbench"]["testcase"] == testcase
    assert req["testbench"]["search_path"] == str(tmp_path)
    assert "verified" in done.stdout


def test_render_refuses_a_netlist_that_is_not_the_one_the_report_names(tmp_path):
    """A re-run in a dirty flow/build/<core>/ must not simulate a stale netlist."""
    netlist = tmp_path / "core_synth.v"
    netlist.write_text("module m; endmodule\n")
    report = _synth_report(tmp_path, netlist, sha="0" * 64)
    done, out = _render(tmp_path, report, TEMPLATES[0])
    assert done.returncode != 0
    assert "stale netlist" in done.stderr
    assert not out.exists(), "no request is written when the netlist is not believed"


def test_render_refuses_a_synthesis_that_did_not_succeed(tmp_path):
    netlist = tmp_path / "core_synth.v"
    netlist.write_text("module m; endmodule\n")
    report = _synth_report(tmp_path, netlist)
    report.write_text(json.dumps({**json.loads(report.read_text()), "status": "error"}))
    done, _ = _render(tmp_path, report, TEMPLATES[0])
    assert done.returncode != 0 and "not ok" in done.stderr


def test_render_refuses_a_source_that_does_not_exist(tmp_path):
    missing = tmp_path / "gone_synth.v"
    missing.write_text("module m; endmodule\n")
    report = _synth_report(tmp_path, missing)
    missing.unlink()
    done, _ = _render(tmp_path, report, TEMPLATES[0])
    assert done.returncode != 0


# --- option pairs that cannot mean anything ----------------------------------

@pytest.mark.parametrize("core", ["aes", "sha256"])
@pytest.mark.parametrize("args", [["--sim-only", "--gate-level"],
                                  ["--sim-only", "--record"]])
def test_run_sh_rejects_the_impossible_option_pairs(core, args):
    """Rejected before a bench runs, so it reads as a usage error, not a flow bug."""
    done = subprocess.run([str(REPO / "verification/rtl" / core / "run.sh"), *args],
                          capture_output=True, text=True)
    assert done.returncode == 2, done.stdout
    assert "mutually exclusive" in done.stderr


def test_gate_level_is_not_on_ci_s_path():
    """CI asks each core for --sim-only and --negative-control; neither is --gate-level,
    and --sim-only --gate-level is refused outright by the test above."""
    ci = (REPO / "scripts/ci-verify.sh").read_text()
    assert "--gate-level" not in ci
    assert "--sim-only" in ci and "--negative-control" in ci


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.parent.name)
def test_gate_template_runs_the_same_bench_and_toplevel_as_the_rtl_request(template):
    """AC1 is "the SAME cocotb testbench against the netlist", so the gate request
    may differ from the RTL one in its sources and delay model -- never in which
    bench or which design it elaborates. core_flow_gate also derives the bench
    file it coverage-checks from sim-request.json, so a drift here would check
    the wrong file."""
    gate = json.loads(re.sub(r"@[A-Z_]+@", "x", template.read_text()))
    rtl = json.loads((template.parent / "sim-request.json").read_text())
    assert gate["hdl_toplevel"] == rtl["hdl_toplevel"]
    assert gate["testbench"]["module"] == rtl["testbench"]["module"]
    assert gate["engine"] == rtl["engine"] == "icarus"
    assert gate["options"]["random_seed"] == rtl["options"]["random_seed"]
    assert gate["options"]["timescale"] == rtl["options"]["timescale"]


def test_an_empty_run_list_refuses_the_run():
    """Everything excluded would pass a naive coverage check and run nothing."""
    bench = REPO / "verification/rtl/aes/test_aes_core.py"
    out = run_snippet("_GATE_COVERAGE_PY", str(bench), "", "test_aes_core=all of it")
    assert out.returncode != 0 and "proves nothing" in out.stderr


def test_gate_level_without_a_testcase_list_names_the_contract(tmp_path):
    """GATE_LEVEL=1 with no GATE_TESTCASES must explain itself, not die on set -u."""
    script = tmp_path / "drive.sh"
    script.write_text(
        "set -euo pipefail\n"
        'HERE="%s/verification/rtl/aes"\nNAME=aes\nGATE_LEVEL=1\n'
        'source "%s/flow/common/core_flow.sh"\ncore_flow_gate\n' % (REPO, REPO))
    done = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert done.returncode == 2
    assert "GATE_TESTCASES names no testcase" in done.stderr
