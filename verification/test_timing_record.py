"""The multi-core timing record's freshness guard, against synthetic scratch.

make_timing_record.py is the repo's first generator that reads a SIBLING
run's gitignored build scratch (issue #218): either core's
run.sh --timing --record consumes both cores' flow/build/<core>/sta*.json,
so a record can stamp revision Y while quoting a core measured at revision
X, within one tool and liberty-deck generation -- exactly what the
generator's engine_version and deck checks cannot see. The run therefore
stamps the inputs it measured into flow/build/<core>/sta-inputs.json
(core_flow_sta_inputs in flow/common/core_flow.sh), and the reader
recomputes every stamped hash before recording.

These tests run the real writer (sourced from core_flow.sh) and the real
reader (make_timing_record._load_run_outputs) over a scratch repo with
fabricated klt responses -- no PDK, no openroad -- the way the six
pre-existing guards were exercised on the filing of #218.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "flow/common"))
import record_lib  # noqa: E402
import make_timing_record  # noqa: E402

CORES = (("aes", "aes_core"), ("sha256", "sha256_core"))


def _stamped(core: str) -> set[str]:
    """What core_flow_sta_inputs must stamp for `core`: that core's RTL
    (resolved from its sta-synth-request.json's sources), both request
    templates, its run.sh, and the shared flow helper that produces the
    number. The helpers record_lib.shared_inputs() already derives at record
    time (record_lib.py, setup-env.sh, the generator's own directory) stay
    out of the stamp -- they are the record side's business, not the run's."""
    return {
        f"rtl/{core}/{core}_core.v",
        f"verification/rtl/{core}/run.sh",
        f"verification/rtl/{core}/sta-request.json",
        f"verification/rtl/{core}/sta-synth-request.json",
        "flow/common/core_flow.sh",
    }


TRACKED = {
    "rtl/aes/aes_core.v": "module aes_core; endmodule\n",
    "rtl/sha256/sha256_core.v": "module sha256_core; endmodule\n",
    "verification/rtl/aes/run.sh": "#!/usr/bin/env bash\n",
    "verification/rtl/sha256/run.sh": "#!/usr/bin/env bash\n",
    "verification/rtl/aes/sta-request.json":
        json.dumps({"constraints": {"clock_period_ns": 20}}),
    "verification/rtl/sha256/sta-request.json":
        json.dumps({"constraints": {"clock_period_ns": 20}}),
    "verification/rtl/aes/sta-synth-request.json":
        json.dumps({"sources": ["../../../rtl/aes/aes_core.v"]}),
    "verification/rtl/sha256/sta-synth-request.json":
        json.dumps({"sources": ["../../../rtl/sha256/sha256_core.v"]}),
    "flow/common/core_flow.sh": "# shared flow helpers\n",
}

_GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(_GIT + ["-C", str(repo), *args],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _run_writer(repo: Path, core: str) -> None:
    """core_flow_sta_inputs against the scratch repo: core_flow.sh sourced
    the way a run.sh sources it (NAME and HERE set first), under set -euo
    pipefail like every run.sh."""
    script = (
        "set -euo pipefail\n"
        f"NAME={core}\n"
        f"HERE={repo}/verification/rtl/{core}\n"
        f"source {repo}/flow/common/core_flow.sh\n"
        "core_flow_sta_inputs\n"
    )
    subprocess.run(["bash", "-c", script], capture_output=True, check=True)


def _fabricate_run(repo: Path, core: str) -> None:
    build = repo / "flow/build" / core
    build.mkdir(parents=True, exist_ok=True)
    (build / "sta-synth.json").write_text(json.dumps({"status": "ok"}))
    (build / "sta.json").write_text(
        json.dumps({"status": "ok", "timing_status": "constrained"}))


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    """A committed scratch repo holding every stamped input, both cores'
    fabricated responses, and both cores' sidecars from the real writer."""
    monkeypatch.setattr(record_lib, "REPO", tmp_path)
    for rel, text in TRACKED.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    # The real flow helper: the stamp comes from the real
    # core_flow_sta_inputs, not from a stub (TRACKED's stand-in only keeps
    # the path present for the reader's recomputation).
    shutil.copyfile(REPO / "flow/common/core_flow.sh", tmp_path / "flow/common/core_flow.sh")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "rtl", "verification", "flow")
    _git(tmp_path, "commit", "-q", "-m", "inputs")
    for core, _ in CORES:
        _fabricate_run(tmp_path, core)
        _run_writer(tmp_path, core)
    return tmp_path


def _load():
    return make_timing_record._load_run_outputs()


def _refuses(capsys, *needles: str) -> str:
    """_load_run_outputs must exit 1 with every `needles` on stderr, and
    nothing may traceback past it."""
    with pytest.raises(SystemExit) as exc:
        _load()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    for needle in needles:
        assert needle in err, err
    return err


def test_sidecar_stamps_exactly_the_core_inputs(scratch):
    head = _git(scratch, "rev-parse", "HEAD")
    for core, _ in CORES:
        side = json.loads(
            (scratch / "flow/build" / core / "sta-inputs.json").read_text())
        assert {e["path"] for e in side["inputs"]} == _stamped(core)
        for entry in side["inputs"]:
            assert entry["content_hash"].startswith("sha256:")
            assert entry["content_hash"] == record_lib.sha256(scratch / entry["path"])
        # The stamped head is a diagnostic, not the comparison key; the writer
        # still records the truth about where the run happened.
        assert side["head"] == head


def test_consistent_scratch_loads(scratch):
    runs = _load()
    assert [(core, top) for core, top, _, _ in runs] == \
        [("aes", "aes_core"), ("sha256", "sha256_core")]


def test_head_advance_without_an_input_change_still_loads(scratch):
    """The false-refusal case the bare rev-equality guard was rejected for:
    HEAD moves for reasons unrelated to the stamped inputs, and a docs-only
    commit between the two cores' runs must not invalidate either."""
    (scratch / "docs").mkdir()
    (scratch / "docs/other.md").write_text("unrelated\n")
    _git(scratch, "add", "docs")
    _git(scratch, "commit", "-q", "-m", "docs only")
    assert len(_load()) == 2


def test_changed_input_refuses_naming_file_and_core(scratch, capsys):
    (scratch / "rtl/aes/aes_core.v").write_text("module aes_core; // changed\n")
    _refuses(capsys, "rtl/aes/aes_core.v",
             "re-run verification/rtl/aes/run.sh --timing first")


def test_only_the_stale_core_is_named(scratch, capsys):
    (scratch / "rtl/sha256/sha256_core.v").write_text("module x; endmodule\n")
    err = _refuses(capsys, "rtl/sha256/sha256_core.v",
                   "re-run verification/rtl/sha256/run.sh --timing first")
    assert "rtl/aes/aes_core.v" not in err
    assert "verification/rtl/aes/run.sh" not in err


def test_missing_sidecar_refuses(scratch, capsys):
    """A scratch dir predating the stamp is exactly the stale case guarded."""
    (scratch / "flow/build/aes/sta-inputs.json").unlink()
    _refuses(capsys, "flow/build/aes/sta-inputs.json is missing",
             "re-run verification/rtl/aes/run.sh --timing first")


def test_malformed_sidecar_refuses(scratch, capsys):
    side = scratch / "flow/build/aes/sta-inputs.json"
    side.write_text("{not json")
    _refuses(capsys, "sta-inputs.json is not a readable input stamp")
    side.write_text(json.dumps({"head": "x", "inputs": "nope"}))
    _refuses(capsys, "sta-inputs.json is not a readable input stamp")
    side.write_text(json.dumps({"head": "x", "inputs": []}))
    _refuses(capsys, "sta-inputs.json is not a readable input stamp")


def test_sidecar_naming_a_missing_path_refuses(scratch, capsys):
    side = scratch / "flow/build/aes/sta-inputs.json"
    doc = json.loads(side.read_text())
    doc["inputs"].append({"path": "rtl/aes/gone.v",
                          "content_hash": "sha256:" + "0" * 64})
    side.write_text(json.dumps(doc))
    _refuses(capsys, "rtl/aes/gone.v",
             "re-run verification/rtl/aes/run.sh --timing first")


def test_missing_sta_synth_response_still_refuses(scratch, capsys):
    (scratch / "flow/build/aes/sta-synth.json").unlink()
    _refuses(capsys, "flow/build/aes/sta-synth.json is missing")


def test_failed_run_still_refuses(scratch, capsys):
    path = scratch / "flow/build/aes/sta.json"
    path.write_text(json.dumps({"status": "error", "timing_status": "constrained"}))
    _refuses(capsys, "aes did not complete")


def test_unconstrained_sta_still_refuses(scratch, capsys):
    path = scratch / "flow/build/aes/sta.json"
    path.write_text(json.dumps({"status": "ok", "timing_status": "unconstrained"}))
    _refuses(capsys, "timing_status is 'unconstrained'")
