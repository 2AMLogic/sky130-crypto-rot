import ast
import importlib.util
import json
import re
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


def test_dirty_input_guard_exempts_setup_env_by_name(tmp_path, monkeypatch):
    """setup-env.sh is hashed into every record but never blocks a run (issue #138)."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    monkeypatch.setattr(record_lib, "REPO", tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / record_lib.SETUP_ENV).write_text("x")
    # Named by the caller or added by shared_inputs(), it is exempt either way.
    assert record_lib.require_clean_inputs([])
    assert record_lib.require_clean_inputs([record_lib.SETUP_ENV])
    # Any other untracked input still refuses, so the exemption is not a blanket one.
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


def _effective(maker) -> list:
    """The inputs a record for `maker` hashes: its INPUTS plus everything derived."""
    return record_lib.shared_inputs(_load(maker).INPUTS, REPO / maker)


@pytest.mark.parametrize("maker", MAKERS)
def test_every_tracked_file_beside_the_generator_is_an_effective_input(maker):
    """The rule is uniform, so own_inputs() derives it (issue #146).

    This is what the hand-written lists were for and what one of them had already
    lost: verification/rtl/hmac/sim-scrub-negctl-request.json is run by the bench
    and was absent from that generator's INPUTS, so the next hmac record would
    have neither hashed nor dirty-checked the request defining its scrub
    negative control.
    """
    directory = Path(maker).parent.as_posix()
    tracked = [p for p in subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z", "--", directory],
        capture_output=True, text=True, check=True).stdout.split("\0")
        if p and p.rsplit("/", 1)[0] == directory]
    assert str(Path(maker).parent / "run.sh") in tracked
    assert maker in tracked
    effective = _effective(maker)
    assert set(tracked) <= set(effective), sorted(set(tracked) - set(effective))


@pytest.mark.parametrize("maker", MAKERS)
def test_generator_does_not_hand_list_its_own_directory(maker):
    """They come from own_inputs(); a hand-copied line is what drifted before."""
    directory = Path(maker).parent.as_posix() + "/"
    assert [p for p in _load(maker).INPUTS if p.startswith(directory)] == []


@pytest.mark.parametrize("maker", MAKERS)
def test_generator_passes_itself_to_record_lib(maker):
    """Nothing is derived for a call that forgets `generator=__file__`."""
    calls = [n for n in ast.walk(ast.parse((REPO / maker).read_text()))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("main", "require_clean_inputs", "write_record")]
    assert calls, maker
    for call in calls:
        kw = {k.arg: k.value for k in call.keywords}
        assert isinstance(kw.get("generator"), ast.Name) and kw["generator"].id == "__file__", \
            f"{maker}:{call.lineno} {call.func.attr}() without generator=__file__"


@pytest.mark.parametrize("maker", MAKERS)
def test_shared_flow_helpers_are_effective_inputs(maker):
    """record_lib.py and setup-env.sh always, core_flow.sh iff run.sh sources it.

    Issue #124 for the first two helpers, #138 for setup-env.sh: every generator
    reports tool pins read out of that file, so every record must hash it.
    """
    effective = _effective(maker)
    assert record_lib.RECORD_LIB in effective
    assert record_lib.SETUP_ENV in effective
    sources = "flow/common/core_flow.sh" in (REPO / Path(maker).parent / "run.sh").read_text()
    assert (record_lib.CORE_FLOW in effective) is sources


@pytest.mark.parametrize("maker", MAKERS)
def test_generator_does_not_hand_list_the_shared_helpers(maker):
    """They come from shared_inputs(); a hand-copied line is what drifted before."""
    inputs = _load(maker).INPUTS
    assert record_lib.RECORD_LIB not in inputs
    assert record_lib.CORE_FLOW not in inputs
    assert record_lib.SETUP_ENV not in inputs


@pytest.mark.parametrize("maker", MAKERS)
def test_generator_does_not_slice_its_inputs(maker):
    """The setup-env exemption is applied by name in require_clean_inputs().

    A positional `INPUTS[:-1]` is what made the same tuple mean three different
    things across the generators (issue #138).
    """
    assert "[:-1]" not in (REPO / maker).read_text()


def test_shared_inputs_appends_the_helpers_and_is_idempotent():
    out = record_lib.shared_inputs(["verification/rtl/aes/run.sh"])
    assert out == ["verification/rtl/aes/run.sh", record_lib.CORE_FLOW,
                   record_lib.RECORD_LIB, record_lib.SETUP_ENV]
    assert record_lib.shared_inputs(out) == out


def test_shared_inputs_omits_core_flow_when_the_flow_does_not_source_it():
    out = record_lib.shared_inputs(["verification/formal/run.sh"])
    assert out == ["verification/formal/run.sh", record_lib.RECORD_LIB, record_lib.SETUP_ENV]


def test_shared_inputs_derives_core_flow_from_the_derived_run_sh():
    """The flow's run.sh is no longer hand-listed, so the core_flow.sh rule now
    reads it out of own_inputs() rather than out of INPUTS (issue #124's rule,
    issue #146's list)."""
    out = record_lib.shared_inputs(["rtl/aes/aes_core.v"],
                                   REPO / "verification/rtl/aes/make_record.py")
    assert out[0] == "rtl/aes/aes_core.v"
    assert out[-1] == record_lib.SETUP_ENV
    assert "verification/rtl/aes/run.sh" in out
    assert record_lib.CORE_FLOW in out
    assert record_lib.shared_inputs(out, REPO / "verification/rtl/aes/make_record.py") == out


# --- own_inputs: the derived own-directory list (issue #146) -----------------


def test_own_inputs_is_tracked_files_only_and_non_recursive(tmp_path, monkeypatch):
    """A gitignored or untracked neighbour is not an input, and a subdirectory is
    a separate experiment: verification/formal/keyladder/ must not fold into
    verification/formal/."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    d = tmp_path / "verification/formal"
    (d / "sub").mkdir(parents=True)
    for rel in ("make_record.py", "run.sh", "p9.sby", "sub/make_record.py", "scratch.log"):
        (d / rel).write_text("x\n")
    (tmp_path / ".gitignore").write_text("*.log\n")
    (d / "leftover.v").write_text("x\n")  # untracked, not ignored
    subprocess.run(["git", "-C", str(tmp_path), "add", ".gitignore", "verification"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "rm", "-q", "--cached", "verification/formal/leftover.v"],
                   check=True)
    monkeypatch.setattr(record_lib, "REPO", tmp_path)

    assert record_lib.own_inputs(d / "make_record.py") == [
        "verification/formal/make_record.py",
        "verification/formal/p9.sby",
        "verification/formal/run.sh",
    ]
    assert record_lib.own_inputs(d / "sub/make_record.py") == ["verification/formal/sub/make_record.py"]


def test_own_inputs_refuses_when_git_cannot_answer(tmp_path, monkeypatch):
    """Fail closed: an unanswerable lookup must not report a short input set."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.setattr(record_lib, "REPO", tmp_path)  # not a git repository
    (tmp_path / "verification").mkdir()
    with pytest.raises(SystemExit, match="refusing to record"):
        record_lib.own_inputs(tmp_path / "verification/make_record.py")


def test_own_inputs_refuses_a_generator_outside_the_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(record_lib, "REPO", tmp_path / "repo")
    with pytest.raises(SystemExit, match="outside"):
        record_lib.own_inputs(tmp_path / "elsewhere/make_record.py")


def test_dirty_input_guard_refuses_an_untracked_file_beside_the_generator(tmp_path, monkeypatch):
    """own_inputs() names only tracked files, so the guard checks the directory too:
    a new bench file nobody committed refuses the record instead of being skipped."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    d = tmp_path / "verification/rtl/aes"
    d.mkdir(parents=True)
    (d / "make_record.py").write_text("x\n")
    _git(tmp_path, "add", "verification")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
    monkeypatch.setattr(record_lib, "REPO", tmp_path)
    assert record_lib.require_clean_inputs([], d / "make_record.py")

    (d / "sim-new-request.json").write_text("{}\n")
    with pytest.raises(SystemExit, match="sim-new-request.json"):
        record_lib.require_clean_inputs([], d / "make_record.py")


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
    """A throwaway REPO holding the shared inputs shared_inputs() always adds."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for rel, text in ((record_lib.RECORD_LIB, "# stand-in for the real record_lib.py\n"),
                      (record_lib.SETUP_ENV, "# stand-in for the real setup-env.sh\n")):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
        _git(tmp_path, "add", rel)
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


# --- the shared klt-provenance bullet (issue #141) ---------------------------


def _prov_and_versions():
    prov = {"klt_version": "1.2.3",
            "pdk": {"name": "sky130A", "version": "pdkver"},
            "deck": {"name": "tt_025C_1v80", "content_hash": "sha256:deck"},
            "input": {"content_hash": "sha256:in"}}
    versions = {"klt_pin": "1.2.3", "yosys": "0.57", "yowasp_yosys": "0.57.0.dev",
                "yosys_wasm": "sha256:wasm", "icarus": "13.0", "cocotb": "1.9.2",
                "ciel": "2.0.0", "python": "3.12.3"}
    return prov, versions


def test_klt_provenance_bullet_is_one_line_naming_every_tool():
    bullet = record_lib.klt_provenance_bullet(*_prov_and_versions())
    assert bullet == (
        "- **klt provenance**: klt `1.2.3` pinned at `1.2.3`; pdk `sky130A` pdkver; "
        "liberty `tt_025C_1v80` sha256:deck; synthesis input sha256:in. "
        "Tool versions: Yosys 0.57 (yowasp-yosys 0.57.0.dev, `yosys.wasm` sha256:wasm), "
        "Icarus Verilog 13.0, cocotb 1.9.2, ciel 2.0.0, Python 3.12.3.")
    assert "\n" not in bullet  # a body interpolates it as a single line


@pytest.mark.parametrize("maker", MAKERS)
def test_generator_does_not_hand_write_the_klt_provenance_bullet(maker):
    """Five byte-identical copies is what issue #141 found; main() builds it once."""
    text = (REPO / maker).read_text()
    assert "- **klt provenance**: klt `{prov[" not in text


# ---------------------------------------------------------------------------
# Gate-level mode (issue #179). The cores that have one are derived from which
# run.sh declares GATE_TESTCASES, not hand-listed, so adding the mode to a
# third core brings it under these tests without anyone remembering to.
GATE_CORES = sorted(
    p.parent.relative_to(REPO).as_posix()
    for p in (REPO / "verification/rtl").glob("*/run.sh")
    if re.search(r"^GATE_TESTCASES=", p.read_text(), re.M))

GATE_JSON = {
    "netlist_path": "verification/rtl/aes/.klt/synthesize/run-abc/aes_core_synth.v",
    "netlist_sha256": "f8e48e9b",
    "instance_count": 30204,
    "cell_models": [],  # filled per test with real paths, which get hashed
    "defines": {"FUNCTIONAL": None, "UNIT_DELAY": "#1"},
    "sdf": None,
    "status": "pass",
    "testcases": {"test_aes_core": {"passed_count": 1, "test_count": 1,
                                    "tests": [{"sim_time_ns": 74810.0}]}},
    "excluded": {},
}


def _gate(tmp_path, **over):
    """A gate.json dict whose cell_models are real files, so sha256() can run."""
    gate = {**GATE_JSON, **over}
    if not gate["cell_models"]:
        model = tmp_path / "primitives.v"
        model.write_text("// cell models\n")
        gate["cell_models"] = [str(model)]
    (tmp_path / "sky130A").mkdir(exist_ok=True)
    (tmp_path / "sky130A/SOURCES").write_text("open_pdks f6eeac7dad08\n")
    return gate


def test_open_pdks_revision_reads_the_installed_tree(tmp_path):
    (tmp_path / "sky130A").mkdir()
    (tmp_path / "sky130A/SOURCES").write_text("sky130_fd_sc_hd xyz\nopen_pdks f6eeac7\n")
    assert record_lib.open_pdks_revision(tmp_path) == "f6eeac7"


def test_open_pdks_revision_refuses_a_tree_that_names_none(tmp_path):
    (tmp_path / "sky130A").mkdir()
    (tmp_path / "sky130A/SOURCES").write_text("sky130_fd_sc_hd xyz\n")
    with pytest.raises(SystemExit, match="no open_pdks revision"):
        record_lib.open_pdks_revision(tmp_path)


def test_no_gate_run_keeps_the_pre_179_sentence_and_adds_no_bullet(tmp_path):
    """A record must never imply a netlist simulation it does not have."""
    provenance, bullet = record_lib.gate_level_bullets(None, tmp_path, "aes")
    assert provenance.endswith("No gate-level simulation was run.")
    assert provenance.startswith("RTL, pre-synthesis simulation (Icarus);")
    assert bullet == ""


def test_gate_bullet_states_netlist_models_delay_model_and_no_sdf(tmp_path):
    """AC4: netlist hash, cell-model source and hash, delay model, pre-layout/no SDF."""
    gate = _gate(tmp_path)
    provenance, bullet = record_lib.gate_level_bullets(gate, tmp_path, "aes")
    assert "the same bench was then re-run against that netlist" in provenance.lower()
    assert "sha256:f8e48e9b" in bullet                      # netlist hash
    assert "30204 `sky130_fd_sc_hd` instances" in bullet
    assert "`primitives.v` " + record_lib.sha256(Path(gate["cell_models"][0])) in bullet
    assert "open_pdks `f6eeac7dad08`" in bullet              # the installed revision
    assert "`FUNCTIONAL`" in bullet and "`UNIT_DELAY` = `#1`" in bullet
    assert "**Pre-layout, no SDF back-annotation**" in bullet
    assert "`options.sdf` is `null`" in bullet, "a JSON field reads as JSON, not Python None"
    assert "None" not in bullet
    assert "makes NO timing claim" in bullet
    assert "the sha256 above, not the path, is the netlist's identity" in bullet
    assert bullet.startswith("- **Gate-level simulation**:")
    assert bullet.endswith("\n")


def test_gate_bullet_does_not_use_the_vendored_defines_file(tmp_path):
    """#134's premise: options.defines is native at the pin, so it has no caller."""
    _, bullet = record_lib.gate_level_bullets(_gate(tmp_path), tmp_path, "aes")
    assert "is **not** used" in bullet
    assert "sky130_fd_sc_hd_sim_defines.v" in bullet


def test_gate_bullet_names_every_excluded_testcase_with_its_reason(tmp_path):
    """AC5/AC2: a check not run at gate level is named in the record, not omitted."""
    gate = _gate(tmp_path, excluded={"test_million_a": "about 2M cycles"})
    _, bullet = record_lib.gate_level_bullets(gate, tmp_path, "sha256")
    assert "**not run at gate level**: `test_million_a` (about 2M cycles)" in bullet
    _, none = record_lib.gate_level_bullets(_gate(tmp_path), tmp_path, "aes")
    assert "no testcase of this bench was left out" in none


def test_gate_bullet_names_the_core_s_own_negative_control_command(tmp_path):
    for core in ("aes", "sha256"):
        _, bullet = record_lib.gate_level_bullets(_gate(tmp_path), tmp_path, core)
        assert f"./verification/rtl/{core}/run.sh --gate-level --negative-control" in bullet


def test_gate_bullet_links_the_klayout_tools_tool_gap(tmp_path):
    """The friction protocol: the gap is linked from the record (AC6)."""
    _, bullet = record_lib.gate_level_bullets(_gate(tmp_path), tmp_path, "aes")
    assert "2AMLogic/klayout-tools" in bullet
    assert record_lib._KLT_DEFINES_GAP in bullet
    assert record_lib._KLT_CHAIN_GAP in bullet


def test_at_least_two_cores_have_a_gate_level_mode():
    """Issue #179 delivers it for aes and sha256; guards the derivation above."""
    assert {"verification/rtl/aes", "verification/rtl/sha256"} <= set(GATE_CORES)


@pytest.mark.parametrize("core", GATE_CORES)
def test_gate_core_declares_a_request_template_and_no_static_request(core):
    """The netlist path is per-run, so the request cannot be a committed constant."""
    assert (REPO / core / "sim-gate-request.json.in").is_file()
    assert not (REPO / core / "sim-gate-request.json").exists()


@pytest.mark.parametrize("core", GATE_CORES)
def test_gate_core_generator_does_not_hand_write_the_gate_level_text(core):
    """Both cores say the same things about a netlist run; main() builds them once."""
    text = (REPO / core / "make_record.py").read_text()
    assert "{ctx.gate_provenance}" in text
    assert "{ctx.gate_level}" in text
    assert "No gate-level simulation was run" not in text
    assert "- **Gate-level simulation**" not in text
