"""The DRBG/TRNG formal record states each task's mode, and its Depth honestly.

Issue #224: `sby_depth` collapses "no `config.sby` at all" (sby never wrote one
-- a genuinely broken run) and "a `config.sby` with no `depth` line" (an
unbounded `mode prove` task -- p7_p8.sby/prove and p9.sby/prove, the record's
primary claim) into one None. The generator recorded either without comment, so
a broken run published as evidence and the two unbounded proofs published a bare
Python None that reads as a tooling failure.

The rule now is mode-aware, read from the same resolved config.sby the depth
comes from (issue #165): a run with no config.sby refuses to record, a bounded
(`mode bmc`/`mode cover`) task without a depth refuses to record, and a
depth-less `mode prove` task is the unbounded proof and records as `unbounded` --
never None -- with the net_prove shape (prove + depth) recording that depth
unchanged. The keyladder generator keeps its own blanket guard (every keyladder
task names a depth, including its prove ones) and is deliberately not aligned
with this one (issue #224, out of scope).

The formal flow itself is local-only (PDK, pinned sby, bounded runs past the CI
budget -- see verification/README.md), so this is the only automated check the
generator's verdict rule gets. It exercises the verdict and the Depth-cell
rendering, not the solver: the record-path plumbing (clean-tree check,
tool-version probes) is stubbed, and --check-only pins that a refused run
stops before any of it. The sby_mode reader contract itself lives in
verification/test_record_lib.py, run against record_lib directly (issues
#259, #262, #263); the identity assertions in
test_keyladder_formal_record.py pin this generator's import of it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GENERATOR = "verification/formal/make_record.py"

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


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("drbg_make_record", REPO / GENERATOR)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["drbg_make_record"] = mod
    spec.loader.exec_module(mod)
    return mod


def _out_dir(tmp_path: Path, rows, configs):
    """A flow/build/formal-shaped out dir: results.tsv plus per-task run
    directories carrying the config.sby sby would have written (or none)."""
    out = tmp_path / "flow" / "build" / "formal"
    out.mkdir(parents=True)
    out.joinpath("results.tsv").write_text("".join(rows))
    for (f, t), cfg in configs.items():
        d = out / f"{f[:-4]}_{t}"
        d.mkdir()
        if cfg is not None:
            (d / "config.sby").write_text(cfg)
    return out


def _row(f, t, status, rc_s="0"):
    """One results.tsv line as run.sh writes it (7 tab-separated columns; the
    generator reads file, task, status, rc and the counterexample frame)."""
    return f"{f}\t{t}\t{status}\t{rc_s}\tengine_0 (abc pdr) returned PASS\t-\t3\n"


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
                   {("p9.sby", "bmc"): CONFIG["bmc30"]})
    calls = _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch, check_only=False) == 0
    (experiment, _rev, body) = calls["write_record"][0]
    assert experiment == gen.EXPERIMENT
    assert "| `p9.sby` | `bmc` | PASS | engine_0 (abc pdr) returned PASS | 30 |" in body


def test_bmc_without_a_depth_refuses_to_record(gen, monkeypatch, tmp_path):
    """A bounded task must state the depth it ran at: a passing run with no
    depth still refuses, because the record is append-only (issue #224)."""
    out = _out_dir(tmp_path, [_row("p9.sby", "bmc", "PASS")],
                   {("p9.sby", "bmc"): CONFIG["bmc_no_depth"]})
    calls = _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch) == 1
    assert calls["require_clean_inputs"] == 0
    assert calls["write_record"] == []


def test_cover_without_a_depth_refuses_to_record(gen, monkeypatch, tmp_path):
    out = _out_dir(tmp_path, [_row("p9.sby", "bmc", "PASS")],
                   {("p9.sby", "bmc"): CONFIG["cover_no_depth"]})
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
                   {(sby, task): CONFIG["prove_unbounded"]})
    calls = _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch, check_only=False) == 0
    (_experiment, _rev, body) = calls["write_record"][0]
    assert f"| `{sby}` | `{task}` | PASS | engine_0 (abc pdr) returned PASS | unbounded |" in body
    assert "| None |" not in body


def test_prove_with_a_depth_records_it_unchanged(gen, monkeypatch, tmp_path):
    """The net_prove shape: mode prove AND a depth (resolved from
    @NET_PROVE_DEPTH@) records that depth, not `unbounded`."""
    out = _out_dir(tmp_path, [_row("net_p9.sby", "net_prove", "PASS")],
                   {("net_p9.sby", "net_prove"): CONFIG["prove20"]})
    calls = _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch, check_only=False) == 0
    (_experiment, _rev, body) = calls["write_record"][0]
    assert "| `net_p9.sby` | `net_prove` | PASS | engine_0 (abc pdr) returned PASS | 20 |" in body


def test_inconclusive_net_prove_at_its_depth_still_records(gen, monkeypatch, tmp_path):
    """The PASS_OR_DEPTH rows may end TIMEOUT/UNKNOWN at their depth and are
    recorded as not proven (issue #177): the mode-aware guard must keep that
    path open -- a prove task that names a depth is never the broken case."""
    out = tmp_path / "flow" / "build" / "formal"
    out.mkdir(parents=True)
    out.joinpath("results.tsv").write_text(_row("net_p9.sby", "net_prove", "TIMEOUT"))
    d = out / "net_p9_net_prove"
    d.mkdir()
    (d / "config.sby").write_text(CONFIG["prove20"])
    (d / "logfile.txt").write_text(
        "##   Checking assertions in step 0..\n"
        "##   Trying induction in step 19..\n"
        "##   Checking assertions in step 14..\n"
        "## Status for engine_0: TIMEOUT\n")
    calls = _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch, check_only=False) == 0
    (_experiment, _rev, body) = calls["write_record"][0]
    assert "TIMEOUT -- reached depth 14, not proven" in body
    assert "| `net_p9.sby` | `net_prove` | TIMEOUT -- reached depth 14, not proven | engine_0 (abc pdr) returned PASS | 20 |" in body


def test_record_wording_keeps_the_notes_drops_the_closed_gap(gen, monkeypatch, tmp_path):
    """Issue #129: a newly rendered record states the configured engines and
    `aigsmt none`, keeps the still-active short-TMPDIR synthesis note, and no
    longer claims the venv's sby ships no SMT solver or needs a helper shim
    (setup-env.sh links sby and both helper names from the pinned wheel).
    Records are append-only: this pins the template's wording, not any
    published record, and mints no evidence from synthetic results."""
    out = _out_dir(tmp_path, [_row("p7_p8.sby", "prove", "PASS")],
                   {("p7_p8.sby", "prove"): CONFIG["prove_unbounded"]})
    calls = _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch, check_only=False) == 0
    body = calls["write_record"][0][2]
    assert "`abc pdr`" in body and "`abc bmc3`" in body
    assert "`aigsmt none`" in body
    assert "short `TMPDIR`" in body        # the netlist synthesis note stays
    assert "klayout-tools#5780" in body    # with its upstream reference
    assert "no SMT solver" not in body     # the closed gap is not re-asserted
    assert "formal-bin" not in body        # neither is the removed shim


def test_run_with_no_config_sby_refuses_to_record(gen, monkeypatch, tmp_path):
    """sby never wrote a config.sby: neither the mode nor the depth of what ran
    can be stated, so the run is broken and refuses (issue #224)."""
    out = _out_dir(tmp_path, [_row("p9.sby", "bmc", "ERROR", rc_s="1")],
                   {("p9.sby", "bmc"): None})
    calls = _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch) == 1
    assert calls["require_clean_inputs"] == 0
    assert calls["write_record"] == []


def test_refusal_mentions_why(gen, monkeypatch, capsys, tmp_path):
    out = _out_dir(tmp_path, [_row("p9.sby", "bmc", "PASS")],
                   {("p9.sby", "bmc"): CONFIG["bmc_no_depth"]})
    _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch) == 1
    err = capsys.readouterr().err
    assert "names no depth" in err
    assert "p9.sby bmc" in err


def test_no_config_sby_refusal_mentions_why(gen, monkeypatch, capsys, tmp_path):
    out = _out_dir(tmp_path, [_row("p9.sby", "bmc", "ERROR", rc_s="1")],
                   {("p9.sby", "bmc"): None})
    _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch) == 1
    err = capsys.readouterr().err
    assert "no config.sby" in err


def test_modeless_config_refusal_names_the_case(gen, monkeypatch, capsys, tmp_path):
    """A config.sby that is present but names no `mode` under `[options]`
    refuses too, and the refusal must say THAT: not claim the file is missing
    (issue #243) -- sby_mode's two None meanings get two distinct messages."""
    out = _out_dir(tmp_path, [_row("p9.sby", "bmc", "PASS")],
                   {("p9.sby", "bmc"): CONFIG["no_mode"]})
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
                   {("p7_p8.sby", "reach_valid"): CONFIG["bmc_no_depth"]})
    calls = _stub_record_path(monkeypatch, gen)
    assert _run_gen(gen, out, monkeypatch) == 1
    assert calls["require_clean_inputs"] == 0
    assert calls["write_record"] == []
    err = capsys.readouterr().err
    assert "expected FAIL" not in err          # the expectation was met
    assert "names no depth" in err             # the refusal is the Depth rule
