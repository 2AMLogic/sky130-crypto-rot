import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "flow/common"))
import record_lib  # noqa: E402

# Every record generator in the tree; the shared-helper tests below are
# parametrized over all of them so a new core cannot be added without one.
MAKERS = sorted(p.relative_to(REPO).as_posix()
                for p in (REPO / "verification").rglob("make_record.py"))

PINS = ("KLT_VERSION", "YOWASP_YOSYS_VERSION", "COCOTB_VERSION", "CIEL_VERSION",
        "CIEL_SKY130_VERSION", "Z3_SOLVER_VERSION")


@pytest.mark.parametrize("name", PINS)
def test_pin_resolves_against_setup_env(name):
    assert record_lib.pin(name)


def test_missing_pin_refuses():
    with pytest.raises(SystemExit):
        record_lib.pin("KLT_REV")


def test_pdk_pin_guard_refuses_mismatch(tmp_path):
    (tmp_path / "sky130A").mkdir()
    (tmp_path / "sky130A/SOURCES").write_text("open_pdks 0000000\n")
    with pytest.raises(SystemExit, match="pinned open_pdks"):
        record_lib.check_pdk(tmp_path)
    (tmp_path / "sky130A/SOURCES").write_text("open_pdks " + record_lib.pin("CIEL_SKY130_VERSION") + "\n")
    record_lib.check_pdk(tmp_path)


def test_dirty_input_guard_refuses_untracked(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    monkeypatch.setattr(record_lib, "REPO", tmp_path)
    assert record_lib.require_clean_inputs(["a.txt"])
    (tmp_path / "a.txt").write_text("x")
    with pytest.raises(SystemExit, match="commit it before recording"):
        record_lib.require_clean_inputs(["a.txt"])


def _load(maker: str):
    """The make_record.py at repo-relative `maker`, imported under a unique name."""
    spec = importlib.util.spec_from_file_location(maker.replace("/", "_")[:-3], REPO / maker)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_core_has_a_record_generator():
    assert len(MAKERS) >= 8, MAKERS


@pytest.mark.parametrize("maker", MAKERS)
def test_generator_lists_its_own_run_sh(maker):
    """shared_inputs() reads core_flow.sh use out of the flow's run.sh, so it must be an input."""
    run_sh = str(Path(maker).parent / "run.sh")
    assert (REPO / run_sh).exists()
    assert run_sh in _load(maker).INPUTS


@pytest.mark.parametrize("maker", MAKERS)
def test_shared_flow_helpers_are_effective_inputs(maker):
    """record_lib.py always, core_flow.sh iff the sibling run.sh sources it (issue #124)."""
    effective = record_lib.shared_inputs(_load(maker).INPUTS)
    assert record_lib.RECORD_LIB in effective
    sources = "flow/common/core_flow.sh" in (REPO / Path(maker).parent / "run.sh").read_text()
    assert (record_lib.CORE_FLOW in effective) is sources


@pytest.mark.parametrize("maker", MAKERS)
def test_generator_does_not_hand_list_the_shared_helpers(maker):
    """They come from shared_inputs(); a hand-copied line is what drifted before."""
    inputs = _load(maker).INPUTS
    assert record_lib.RECORD_LIB not in inputs
    assert record_lib.CORE_FLOW not in inputs


def test_shared_inputs_keeps_setup_env_last_and_is_idempotent():
    out = record_lib.shared_inputs(["verification/rtl/aes/run.sh", record_lib.SETUP_ENV])
    assert out == ["verification/rtl/aes/run.sh", record_lib.CORE_FLOW,
                   record_lib.RECORD_LIB, record_lib.SETUP_ENV]
    assert record_lib.shared_inputs(out) == out


def test_shared_inputs_omits_core_flow_when_the_flow_does_not_source_it():
    out = record_lib.shared_inputs(["verification/formal/run.sh"])
    assert out == ["verification/formal/run.sh", record_lib.RECORD_LIB]


# --- supersedes: the predecessor lookup (issue #137) -------------------------
#
# write_record() derives `supersedes` from the tree rather than taking it from a
# caller, so these drive write_record() against a throwaway git repository.
# Predecessors are seeded as files, not by calling write_record() twice: two
# calls in the same second produce the same record id and the second overwrites
# the first.


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _meta(text: str) -> dict:
    return json.loads(text.split("<!-- record-meta\n", 1)[1].split("\n-->", 1)[0])


@pytest.fixture
def temp_repo(tmp_path, monkeypatch):
    """A throwaway REPO holding the one shared input shared_inputs() always adds."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / record_lib.RECORD_LIB).parent.mkdir(parents=True)
    (tmp_path / record_lib.RECORD_LIB).write_text("# stand-in for the real record_lib.py\n")
    _git(tmp_path, "add", record_lib.RECORD_LIB)
    monkeypatch.setattr(record_lib, "REPO", tmp_path)
    return tmp_path


def _seed(repo: Path, experiment: str, *names: str) -> Path:
    d = repo / "verification/records" / experiment / "records"
    d.mkdir(parents=True, exist_ok=True)
    for name in names:
        (d / name).write_text("seed\n")
    return d


def test_first_record_of_an_experiment_supersedes_nothing(temp_repo):
    text = record_lib.write_record("exp", "0" * 40, [], {}, "- **Claim**: x\n").read_text()
    assert _meta(text)["supersedes"] is None
    assert text.splitlines()[-1] == "- **Supersedes**: none"
    assert text.count("**Supersedes**") == 1


def test_record_supersedes_the_newest_tracked_record_of_the_same_experiment(temp_repo):
    """Newest tracked generated record only: not the hand-written id shape, not a
    non-record file, not an untracked leftover, not another experiment's records."""
    _seed(temp_repo, "exp", "20260101-000000-aaaaaaa.md", "20260102-000000-bbbbbbb.md",
          "20260103-ccccccc.md", "README.md")
    _seed(temp_repo, "other", "20260105-000000-eeeeeee.md")
    _git(temp_repo, "add", "verification/records")
    _seed(temp_repo, "exp", "20260104-000000-ddddddd.md")  # untracked, after the add

    text = record_lib.write_record("exp", "0" * 40, [], {}, "- **Claim**: x\n").read_text()
    assert _meta(text)["supersedes"] == "20260102-000000-bbbbbbb"
    assert text.splitlines()[-1] == "- **Supersedes**: 20260102-000000-bbbbbbb"
    assert text.count("**Supersedes**") == 1


def test_failed_predecessor_lookup_refuses_to_write(tmp_path, monkeypatch):
    """Fail closed: an unanswerable lookup must not fall back to `none`."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.setattr(record_lib, "REPO", tmp_path)  # not a git repository
    with pytest.raises(SystemExit, match="refusing to record"):
        record_lib.write_record("exp", "0" * 40, [], {}, "- **Claim**: x\n")
    assert not (tmp_path / "verification").exists()


@pytest.mark.parametrize("maker", MAKERS)
def test_generator_does_not_hand_write_the_supersedes_bullet(maker):
    """One source for the value; six hand-copied literals is what issue #137 found."""
    assert "Supersedes" not in (REPO / maker).read_text()
