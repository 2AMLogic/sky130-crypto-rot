import ast
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

# Every name the pin block assigns, derived rather than hand-copied (issue
# #189): a new pin, a rename or a dropped one moves this test with it, so
# nothing pin() can resolve goes untested. The hand-copied tuple this replaces
# had already lost Z3_BIN_SHA256, which make_record.py resolves only at
# key-ladder record time -- the first signal a rename broke it was the end of
# a full formal run, not this suite.
_BLOCK = record_lib.parse_pins((REPO / record_lib.SETUP_ENV).read_text())
assert _BLOCK is not None, "no pin block in scripts/setup-env.sh"
PINS = tuple(sorted(_BLOCK))


@pytest.mark.parametrize("name", PINS)
def test_pin_resolves_against_setup_env(name):
    assert record_lib.pin(name)


def test_missing_pin_refuses():
    with pytest.raises(SystemExit):
        record_lib.pin("KLT_REV")


def test_pin_does_not_resolve_outside_the_block(tmp_path, monkeypatch):
    """The delimiters are the only definition of a pin (issue #189).

    A later assignment of a pin name -- a fallback, a re-export, a --force
    branch -- is not a pin and must not change what pin() resolves, and a
    name assigned only outside the block is a hard error rather than a silent
    match: the value lands in the tool_versions block of append-only records.
    Before this, pin() scanned the whole script and took the first NAME="
    match in file order.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / record_lib.SETUP_ENV).write_text(
        "# --- pinned versions -- keep in sync with docs/environment.md ----\n"
        'KLT_VERSION="1.0"\n'
        "# ------------------------------------------------------------------\n"
        "\n"
        'PDK_ROOT="${PDK_ROOT:-${HOME}/.ciel}"\n'
        'KLT_VERSION="2.0"\n'
    )
    monkeypatch.setattr(record_lib, "REPO", tmp_path)
    assert record_lib.pin("KLT_VERSION") == "1.0"
    with pytest.raises(SystemExit):
        record_lib.pin("PDK_ROOT")


def test_parse_pins_returns_none_when_the_block_is_absent():
    assert record_lib.parse_pins('KLT_VERSION="1.0"\n') is None


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
    lost: verification/rtl/hmac/sim-scrub-negctl-request.json was run by the bench
    and was absent from that generator's INPUTS, so the next hmac record would
    have neither hashed nor dirty-checked the request defining its scrub
    negative control. That file is gone as of issue #161 -- the control is now
    derived from sim-request.json -- but the rule it motivated still holds for
    every tracked file beside a generator.
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


# --- the config.sby readers: one contract, pinned here (issues #165, #194, ----
# --- #221, #259; consolidated by operator ruling 2026-11-17, issue #263) ------
#
# The whole depth/mode reader contract lives in this file, run against
# record_lib directly. It used to be re-asserted through every generator's
# import of these readers in test_keyladder_formal_record.py; that 3-handle
# parametrization was reversed by the operator ruling (round 20261116-r15,
# slate s3) and the guard against a re-introduced generator-local copy is now
# that file's identity assertions (test_both_generators_use_the_shared_readers).

# A real config.sby, byte-for-byte as the pinned yowasp-yosys wheel
# (YOWASP_YOSYS_VERSION in scripts/setup-env.sh) wrote it for a two-task file whose
# `[options]` read `mode bmc` / `a: depth 5` / `b: depth 7`. Captured from the tool
# rather than hand-written, so a format change in a re-pinned sby breaks these rows
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


def _sby_workdir(tmp_path, config):
    d = tmp_path / "task"
    d.mkdir()
    if config is not None:
        (d / "config.sby").write_text(config)
    return d


@pytest.mark.parametrize("config,expected", [
    # the reader parses the resolved config exactly as sby wrote it (and the
    # drbg-trng file's plain multi-section read: options, engines, script, files)
    (REAL_CONFIG_SBY, 5),
    # sby writes the depth of THIS task, `[tasks]` prefixes already resolved;
    # the reader never resolves `net:` itself
    ("[options]\nmode prove\ndepth 2\n", 2),
    # sby strips a trailing ` #...` from an [options] line; so does the reader
    ("[options]\nmode bmc\ndepth 24  # bounded\n", 24),
    # comment and blank lines inside [options] are skipped
    ("[options]\n# the knob below is p6.sby's own\n\nmode prove\ndepth 16\n", 16),
    # only [options] configures the run: a `depth` word in [script] (e.g. a
    # define) is not the run's depth, even over a depth that is stated
    ("[options]\nmode bmc\ndepth 32\n\n[script]\n"
     "read_verilog -formal -Ddepth 99 dut.v\nprep -top keyladder\n", 32),
    # ...and with no depth in [options] at all, a script `depth` word still
    # reads None -- never the script's 99
    ("[options]\nmode bmc\n\n[script]\nread_verilog -Ddepth 99 dut.v\n", None),
    # sby tests for a header on the comment-stripped line inside its strip
    # sections, so `[script]  # a ] b` still ends [options] mode and a later
    # bare `depth` is not read (issue #194) -- the case the pre-#259
    # raw-line header match got wrong
    ("[options]\ndepth 4\n\n[script]  # a ] b\ndepth 99\n", 4),
    # sby does NOT strip comments inside [script], so `[options]  # trick` there
    # is not a header to sby and must not re-open options mode here either
    ("[options]\nmode bmc\ndepth 4\n\n[script]\nread_verilog tiny.v\n"
     "[options]  # trick\ndepth 99\n", 4),
    # sby does not strip before the first section either, so a commented
    # `[options]` at the very top opens no section and reads no depth
    ("[options]  # not really\nmode bmc\ndepth 4\n", None),
    # sby's [options] reader is a dict assignment: a later line overrides
    ("[options]\ndepth 8\ndepth 16\n", 16),
    # [options] re-entered after [script]: last assignment wins
    ("[options]\ndepth 4\n\n[script]\nx\n\n[options]\ndepth 6\n", 6),
    # no config.sby: sby never wrote one, so no depth
    (None, None),
    # sby defaults depth to 20. A record must state what ran, so None, never 20
    ("[options]\nmode bmc\ntimeout 1500\n", None),
    # a depth that is not all digits is no depth, never a crash: the last
    # assignment in [options] wins whatever it holds, so a trailing non-digit
    # erases an earlier valid depth (sby's [options] reader is a dict
    # assignment) and an earlier non-digit is simply overwritten by a valid one
    ("[options]\ndepth abc\n", None),
    ("[options]\ndepth 7\ndepth 4x\n", None),
    ("[options]\ndepth 4x\ndepth 7\n", 7),
])
def test_sby_depth(tmp_path, config, expected):
    """The one shared config.sby depth reader, pinned once against record_lib."""
    assert record_lib.sby_depth(_sby_workdir(tmp_path, config)) == expected


@pytest.mark.parametrize("config,expected", [
    (REAL_CONFIG_SBY, "bmc"),
    # no config.sby means sby never wrote one: None, and the caller must
    # refuse -- this is the one None that is a broken run, not an unbounded
    # one (issue #224)
    (None, None),
    # only `[options]` configures the run; a `mode` word elsewhere is not one.
    # The `[script]` body carries a literal `mode prove` line, so this fails if
    # `[options]` tracking is removed and every line is scanned (issue #243)
    ("[options]\nmode bmc\n\n[script]\n"
     "mode prove\nread_verilog -formal dut.v\nprep -top top\n", "bmc"),
    # sby strips a trailing ` #...` from an [options] line; so does the reader
    ("[options]\nmode prove  # unbounded\n", "prove"),
    # sby's [options] reader is a dict assignment: a later line overrides
    ("[options]\nmode bmc\nmode prove\n", "prove"),
    # sby does NOT strip comments inside [script], so a commented `[options]`
    # there opens no options block and a later bare `mode` line is not one
    # either. This pins correct behaviour, not a regression fix: the DRBG/TRNG
    # generator-local copy the #259 consolidation replaced matched the header
    # on the raw line before any strip
    ("[options]\nmode bmc\n\n[script]\n# [options]\nmode prove\nprep -top top\n",
     "bmc"),
    # the case the pre-#259 generator-local copy actually got wrong: `[script]`
    # carries a trailing comment, inside a section sby itself comment-strips,
    # so sby -- and the shared reader -- see the header on the stripped line.
    # The old copy matched the header on the raw line, the commented header
    # never matched, `[options]` never closed, and it misread the script's
    # `mode prove` as this task's mode. Fails against the pre-consolidation copy
    ("[options]\nmode bmc\n\n[script]  # a ] b\nmode prove\nprep -top top\n", "bmc"),
])
def test_sby_mode(tmp_path, config, expected):
    """The one shared config.sby mode reader, pinned once against record_lib."""
    assert record_lib.sby_mode(_sby_workdir(tmp_path, config)) == expected


def test_sby_steps_checked_takes_the_max_over_both_checking_lines():
    """The one scrape behind both record families' steps_checked (issue #259):
    the assertion lines a bounded run emits and the cover-reachability line a
    `mode cover` run emits, maximum over all of them; a log with no checking
    line says nothing."""
    text = ("##   Checking assumptions and assertions in step 0..\n"
            "##   Checking cover reachability in step 9..\n"
            "##   Checking assertions in step 14..\n")
    assert record_lib.sby_steps_checked(text) == 14
    assert record_lib.sby_steps_checked("engine killed before any step\n") is None
