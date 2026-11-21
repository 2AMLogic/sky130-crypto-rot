"""Tests for the shared gate-level driver steps in flow/common/core_flow.sh.

The gate-level mode (issue #179) puts three refusals in the flow, and each one
exists because the failure it prevents would otherwise read as a PASS:

  * a netlist left behind by an earlier run would be simulated in place of this
    run's, so the record's netlist hash would name gates nobody ran;
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
import importlib.util
import json
import os
import re
import shlex
import shutil
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


def test_gate_negctl_judges_where_klt_anchors_its_artifacts():
    """A stdin request makes klt anchor its artifacts to the working directory
    (pinned 0.8.0), so the gate-level control must run from ${OUT}/gate-negctl
    and judge the helper's CWD-default evidence path. A carried-over absolute
    path greps a file klt never wrote, the control fails closed, and AC3 cannot
    pass -- which is exactly what carrying the pre-#175 evidence argument across
    the #175 merge did."""
    body = re.search(r"^core_flow_gate_negctl\(\) \{.*?^\}", TEXT, re.S | re.M).group(0)
    cd = re.search(r'^\s*cd "\$\{OUT\}/gate-negctl"$', body, re.M)
    call = re.search(r"core_flow_negctl_one (.*?)(?=\n\s*exit 0)", body, re.S)
    assert cd and call, "the control must judge via core_flow_negctl_one from ${OUT}/gate-negctl"
    assert cd.start() < call.start(), "the cd comes before the helper call"
    assert "results_icarus.xml" not in call.group(1), \
        "no evidence argument: the helper's CWD default names where klt writes"
    assert "request.json" in call.group(1), "a relative base request, resolved by the cd"


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


# --- the P&R runner: stage bound, freshness first, full-route refusal -------
#
# flow/pnr/crypto_rot_top/run.sh (issue #295, the pre-route half of #47) puts
# four refusals/derivations in the flow, and each exists because the failure
# it prevents would otherwise read as a PASS or silently lose the work:
#
#   * the stale-netlist guard must run before ANY klt invocation, so a stale
#     netlist can never produce fresh P&R evidence or a record;
#   * --through-cts must derive EXACTLY a target_stage "cts" request over the
#     committed netlist bytes -- a derived document that stopped resolving
#     them would place a stale netlist silently;
#   * bare --record (the full-route contract) must refuse on a pin without
#     single-unit batch dispatch and never start a local route (4.5-6 h wall,
#     and one attempt already outlived its step holding the output lock);
#   * the future batch command must be explicit --backend batch with a
#     job timeout sized above the measured route time.
#
# They are tested against the REAL run.sh in a stub repo (fake .venv, stub
# check-fresh.sh, stub klt) rather than by reading the script, so the wiring
# -- not just the prose -- is what's asserted. Like the gate-level tests
# above: the real runs take half an hour and are off CI's path.

PNR_RUN = REPO / "flow/pnr/crypto_rot_top/run.sh"
PNR_REQUEST = REPO / "layout/place-and-route.json"
PNR_NETLIST = "verification/rtl/crypto_rot_top/netlist/crypto_rot_top_synth.v"

_KLT_STUB = """#!%(python)s
# Answers as `klt place-and-route` would for the request it was handed: the
# stage comes from the request document itself and the input hash from the
# netlist that document resolves -- so a derived request that stopped
# resolving the committed netlist fails here, visibly.
import hashlib, json, os, sys
with open(os.environ["STUB_LOG"], "a") as fh:
    fh.write("klt " + " ".join(sys.argv[1:]) + "\\n")
req_path = next(a for a in sys.argv[1:] if not a.startswith("-") and a.endswith(".json"))
base = os.path.dirname(os.path.abspath(req_path))
req = json.load(open(req_path))
net = req["netlist"]
net = net if os.path.isabs(net) else os.path.normpath(os.path.join(base, net))
h = hashlib.sha256(open(net, "rb").read()).hexdigest()
stage = req.get("target_stage", "route")
scratch = os.path.join(base, ".klt", "stub")
os.makedirs(scratch, exist_ok=True)
repo = os.environ["STUB_REPO"]
def envelope(path):
    return {"path": os.path.relpath(path, repo), "scope": "repo"}
resp = {
    "status": "ok", "stage_reached": stage, "hdl_toplevel": "crypto_rot_top",
    "engine": "openroad", "engine_version": "stub",
    "die_area_um2": 1.25, "core_area_um2": 1.0, "utilization_pct": 41.7,
    "worst_slack_ns": None, "warnings": [],
    "unrouted_def_path": None, "def_path": None, "gds_path": None,
    "verilog_path": None,
    "power": {"placed": {"status": "complete", "tapcells": 40,
                          "endcaps": 30, "special_nets": 2, "missing": []}},
    "provenance": {
        "klt_version": "0.8.0-stub",
        "pdk": {"name": "sky130A", "version": "stub"},
        "deck": {"name": "sky130_fd_sc_hd__tt_025C_1v80",
                  "content_hash": "sha256:" + "0" * 64},
        "input": {"content_hash": "sha256:" + h},
    },
}
if stage == "cts":
    cts_def = os.path.join(scratch, "crypto_rot_top.cts.def")
    with open(cts_def, "w") as fh:
        fh.write("COMPONENTS 3 ;\\n- a sky130_fd_sc_hd__buf_1 ;\\n"
                 "- b sky130_fd_sc_hd__buf_2 ;\\n- c sky130_fd_sc_hd__dfxtp_1 ;\\n"
                 "END COMPONENTS\\n")
    resp["unrouted_def_path"] = envelope(cts_def)
else:
    paths = {}
    for ext in ("def", "gds", "v"):
        paths[ext] = os.path.join(scratch, "crypto_rot_top." + ext)
        with open(paths[ext], "w") as fh:
            fh.write("stub " + ext + "\\n")
    resp["def_path"] = envelope(paths["def"])
    resp["gds_path"] = envelope(paths["gds"])
    resp["verilog_path"] = envelope(paths["v"])
json.dump(resp, sys.stdout, indent=2)
"""

_FRESH_STUB = """#!/usr/bin/env bash
echo "freshness-guard-ran" >> %(log)s
echo "check-fresh: fresh (stub)"
exit %(rc)s
"""

# The venv python3 stub: real Python for everything else run.sh does with it
# (the JSON helpers and the request derivation are code under test), and the
# one controlled answer the capability probe asks for -- see the stub's own
# header for how the probe's invocation shape is recognized.
_PY_PROBE_STUB = """#!/usr/bin/env bash
# `python3 -` (stdin heredoc, the capability probe's exact shape -- nothing
# else in run.sh invokes it that way) gets the controlled answer; every other
# invocation is real Python, so the JSON helpers and the request derivation
# stay code under test.
if [ "$#" -eq 1 ] && [ "$1" = "-" ]; then exit %(probe_rc)s; fi
exec %(python)s "$@"
"""


def _pnr_repo(tmp_path, *, probe_rc=0, fresh_rc=0):
    """A minimal repo around the REAL run.sh, with stub .venv tools.

    Everything run.sh checks for exists; klt, the capability probe and
    check-fresh.sh append to one log, so "the guard runs first" is asserted
    from the log's order, not assumed.
    """
    repo = tmp_path / "repo"
    flow = repo / "flow/pnr/crypto_rot_top"
    flow.mkdir(parents=True)
    shutil.copy2(PNR_RUN, flow / "run.sh")
    (repo / "layout").mkdir(parents=True)
    shutil.copy2(PNR_REQUEST, repo / "layout/place-and-route.json")
    net = repo / PNR_NETLIST
    net.parent.mkdir(parents=True)
    net.write_text("module crypto_rot_top; endmodule\n")
    (net.parent / "synthesize-envelope.json").write_text(json.dumps(
        {"netlist_sha256": "sha256:"
         + hashlib.sha256(net.read_bytes()).hexdigest()}))
    fresh = net.parent / "check-fresh.sh"
    fresh.write_text(_FRESH_STUB % {"log": shlex.quote(str(tmp_path / "calls.log")),
                                    "rc": fresh_rc})
    fresh.chmod(0o755)
    (repo / "spec").mkdir()
    (repo / "spec/target-spec.md").write_text(
        "| Item | Target |\n|---|---|\n"
        "| Area budget | <= 0.50 mm^2 core at 40 % utilization "
        "(placeholder budget, to be re-set from the first SYNTH report; "
        "not a result) | 0.75 mm^2 |\n")
    venv_bin = repo / ".venv/bin"
    venv_bin.mkdir(parents=True)
    klt = venv_bin / "klt"
    klt.write_text(_KLT_STUB % {"python": sys.executable})
    klt.chmod(0o755)
    py = venv_bin / "python3"
    py.write_text(_PY_PROBE_STUB % {"probe_rc": probe_rc,
                                    "python": sys.executable})
    py.chmod(0o755)
    return repo


def _pnr_run(repo, tmp_path, *args):
    """Run the real run.sh from OUTSIDE the repo root, as an operator would."""
    env = dict(os.environ, STUB_LOG=str(tmp_path / "calls.log"), STUB_REPO=str(repo))
    env.pop("KLT_SIM_BACKEND", None)
    return subprocess.run(
        ["bash", str(repo / "flow/pnr/crypto_rot_top/run.sh"), *args],
        capture_output=True, text=True, cwd=tmp_path, env=env)


def _pnr_log(tmp_path):
    log = tmp_path / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def _pnr_out(repo, name=""):
    out = repo / "flow/build/pnr/crypto_rot_top"
    return out / name if name else out


def test_through_cts_bounds_the_stage_and_guards_freshness_first(tmp_path):
    repo = _pnr_repo(tmp_path)
    done = _pnr_run(repo, tmp_path, "--through-cts")
    assert done.returncode == 0, done.stderr
    log = _pnr_log(tmp_path)
    assert log[0] == "freshness-guard-ran", "the stale-netlist guard runs first"
    klt_line = next(line for line in log if line.startswith("klt "))
    assert "--backend local" in klt_line, "the stage-bounded run stays local"
    derived = _pnr_out(repo, "cts-request.json")
    req = json.loads(derived.read_text())
    assert req["target_stage"] == "cts", "the stage bound is the request's own"
    resolved = (derived.parent / req["netlist"]).resolve()
    committed = (repo / PNR_NETLIST).resolve()
    assert resolved == committed, \
        "the derived request still resolves the committed netlist"
    pnr = json.loads(_pnr_out(repo, "pnr.json").read_text())
    assert pnr["stage_reached"] == "cts"


def test_a_stale_netlist_prevents_any_invocation_and_record(tmp_path):
    repo = _pnr_repo(tmp_path, fresh_rc=3)
    done = _pnr_run(repo, tmp_path, "--through-cts", "--record")
    assert done.returncode != 0
    assert "STALE" in done.stderr
    assert not [l for l in _pnr_log(tmp_path) if l.startswith("klt ")], \
        "no klt invocation after a failed guard"
    assert not _pnr_out(repo, "pnr.json").exists()
    assert not (repo / "verification/records").exists(), "no record either"


def test_full_route_refuses_without_single_unit_batch(tmp_path):
    repo = _pnr_repo(tmp_path, probe_rc=1)
    done = _pnr_run(repo, tmp_path, "--record")
    assert done.returncode != 0
    assert "--local-full-route" in done.stderr, "the refusal names the opt-in"
    assert "klayout-tools#6897" in done.stderr
    assert "klayout-tools#6898" in done.stderr
    assert not [l for l in _pnr_log(tmp_path) if l.startswith("klt ")], \
        "no local route call, no batch dispatch"
    assert not _pnr_out(repo, "pnr.json").exists(), "no record evidence either"
    assert not (repo / "layout/place-and-route-envelope.json").exists()
    assert not _pnr_log(tmp_path), "a refusal spends nothing, not even the guard"


def test_full_route_batches_once_the_pin_supports_it(tmp_path):
    repo = _pnr_repo(tmp_path, probe_rc=0)
    done = _pnr_run(repo, tmp_path, "--record")
    assert done.returncode == 0, done.stderr
    log = _pnr_log(tmp_path)
    assert log[0] == "freshness-guard-ran", "guard first on the batch path too"
    klt_line = next(l for l in log if l.startswith("klt "))
    assert "--backend batch" in klt_line, "the dispatch is explicit batch"
    req = json.loads(_pnr_out(repo, "route-batch-request.json").read_text())
    assert req["target_stage"] == "route"
    assert req["batch"]["job_timeout_s"] == 36000, \
        "the timeout is sized above the 4.5-6 h measured route estimate"
    # the expensive output is staged out of gitignored scratch
    assert (repo / "layout/crypto_rot_top.gds").exists()
    assert (repo / "layout/place-and-route-envelope.json").exists()


def test_local_full_route_opt_in_runs_the_committed_request_unchanged(tmp_path):
    repo = _pnr_repo(tmp_path)
    done = _pnr_run(repo, tmp_path, "--record", "--local-full-route")
    assert done.returncode == 0, done.stderr
    klt_line = next(l for l in _pnr_log(tmp_path) if l.startswith("klt "))
    assert " layout/place-and-route.json" in klt_line, \
        "the committed request itself runs, not a derived copy"
    assert "--backend local" in klt_line
    assert not _pnr_out(repo, "route-batch-request.json").exists()


def test_through_cts_and_local_full_route_cannot_combine(tmp_path):
    repo = _pnr_repo(tmp_path)
    done = _pnr_run(repo, tmp_path, "--through-cts", "--local-full-route")
    assert done.returncode == 2
    assert _pnr_log(tmp_path) == [], "a usage error starts nothing"


def test_no_mode_is_a_usage_error_not_a_full_route(tmp_path):
    """#47's script defaulted to a scratch FULL route; that default must not
    survive -- a bare invocation starting a 6-hour local route is exactly the
    surprise this issue removes."""
    repo = _pnr_repo(tmp_path)
    done = _pnr_run(repo, tmp_path)
    assert done.returncode == 2
    assert _pnr_log(tmp_path) == []


# --- the P&R record generator: refusals and the honest-count/label rules ----

def _pnr_record_module():
    spec = importlib.util.spec_from_file_location(
        "pnr_make_record", REPO / "flow/pnr/crypto_rot_top/make_record.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_count_def_components_reads_the_components_section(tmp_path):
    mod = _pnr_record_module()
    d = tmp_path / "top.cts.def"
    d.write_text("VERSION 5.8 ;\nCOMPONENTS 3 ;\n"
                 "- a sky130_fd_sc_hd__buf_1 + PLACED ( 1 2 ) N ;\n"
                 "- b sky130_fd_sc_hd__buf_2 ;\n"
                 "  - c sky130_fd_sc_hd__dfxtp_1 ;\n"
                 "END COMPONENTS\nEND DESIGN\n")
    assert mod.count_def_components(d) == 3, "continuation lines count once"
    d.write_text("VERSION 5.8 ;\nEND DESIGN\n")
    with pytest.raises(SystemExit, match="COMPONENTS"):
        mod.count_def_components(d)


def test_the_record_refuses_a_run_that_stopped_short_of_cts(tmp_path, monkeypatch, capsys):
    mod = _pnr_record_module()
    monkeypatch.setattr(mod, "OUT_DIR", tmp_path)
    (tmp_path / "freshness.txt").write_text(
        "check-fresh: fresh (byte-identical to the committed netlist)\n")
    (tmp_path / "pnr.json").write_text(json.dumps(
        {"status": "ok", "stage_reached": "place",
         "power": {"placed": {"status": "complete"}}}))
    with pytest.raises(SystemExit):
        mod._load_run()
    assert "through cts" in capsys.readouterr().err
    (tmp_path / "pnr.json").write_text(json.dumps(
        {"status": "ok", "stage_reached": "cts",
         "power": {"placed": {"status": "partial", "missing": ["tapcells"]}}}))
    with pytest.raises(SystemExit):
        mod._load_run()
    assert "power delivery" in capsys.readouterr().err


def test_timing_figures_are_labelled_pre_route_estimates():
    mod = _pnr_record_module()
    absent = mod._timing_note({"worst_slack_ns": None}, 20.0)
    assert "not measured" in absent and "STA is #50" in absent
    estimate = mod._timing_note({"worst_slack_ns": -1.25}, 20.0)
    assert "PRE-ROUTE ESTIMATE" in estimate
    assert "target, unmeasured" in estimate
