"""Selftests for scripts/ci-changed.sh, ci.yml's shared changed-path gate.

Each case runs the gate in a throwaway git repo with an `origin/main` and a
working branch, the way ci.yml's checkout sees a PR (fetch-depth: 0 provides
origin/<base_ref>). Contract under test (issue #283):

* pull_request     diffs origin/$BASE_REF...HEAD, as the inline steps did
* merge_group      diffs $BASE_SHA...$HEAD_SHA -- the merge queue's trial
                   merge vs the event payload's base (github.base_ref is
                   empty on merge_group)
* other events     run=true without consulting git
* fail closed      an empty or unresolvable base, or a failing git diff,
                   exits non-zero and never prints run=false -- the fail-open
                   (`if git diff | grep -q` reads a failed diff as "no
                   match") this script replaces

Pattern adopted from sky130-comparator#332's selftest growth (its gate is a
different check, so nothing is imported; see 2am/REUSE.md, "One source").
Stdlib only besides pytest.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "ci-changed.sh"

# ci.yml's `verify` job filter, byte-identical to the workflow's step.
VERIFY_REGEX = (
    r"^(rtl/|verification/|flow/|scripts/(setup-env|ci-verify)\.sh$"
    r"|\.github/workflows/ci\.yml$)"
)


def _git(repo, *args):
    out = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """origin/main + a `pr` branch checked out, both workflows' base shape."""
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(origin)],
        check=True, capture_output=True,
    )
    work = tmp_path / "work"
    subprocess.run(
        ["git", "clone", "-q", str(origin), str(work)],
        check=True, capture_output=True,
    )
    _git(work, "config", "user.email", "ci-changed@test.invalid")
    _git(work, "config", "user.name", "ci-changed selftest")
    (work / "rtl").mkdir()
    (work / "rtl" / "aes_core.v").write_text("module aes_core(); endmodule\n")
    (work / "docs").mkdir()
    (work / "docs" / "note.md").write_text("note\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "base")
    _git(work, "push", "-q", "origin", "main")
    _git(work, "checkout", "-qb", "pr")
    return work


def _commit(repo, relpath, text):
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"edit {relpath}")


def _run(repo, regex=VERIFY_REGEX, **env):
    full = {
        **os.environ,
        "EVENT_NAME": "",
        "BASE_REF": "",
        "BASE_SHA": "",
        "HEAD_SHA": "",
        **env,
    }
    return subprocess.run(
        ["sh", str(SCRIPT), regex], cwd=repo, env=full, capture_output=True, text=True
    )


def _base(repo):
    return _git(repo, "rev-parse", "origin/main")


def _head(repo):
    return _git(repo, "rev-parse", "HEAD")


def test_pull_request_matching_change_runs(repo):
    _commit(repo, "rtl/new.v", "x\n")
    r = _run(repo, EVENT_NAME="pull_request", BASE_REF="main")
    assert r.returncode == 0
    assert r.stdout == "run=true\n"


def test_pull_request_non_matching_change_skips(repo):
    _commit(repo, "docs/other.md", "x\n")
    r = _run(repo, EVENT_NAME="pull_request", BASE_REF="main")
    assert r.returncode == 0
    assert r.stdout == "run=false\n"


def test_merge_group_matching_change_runs(repo):
    _commit(repo, "rtl/new.v", "x\n")
    r = _run(
        repo, EVENT_NAME="merge_group", BASE_SHA=_base(repo), HEAD_SHA=_head(repo)
    )
    assert r.returncode == 0
    assert r.stdout == "run=true\n"


def test_merge_group_non_matching_change_skips(repo):
    _commit(repo, "docs/other.md", "x\n")
    r = _run(
        repo, EVENT_NAME="merge_group", BASE_SHA=_base(repo), HEAD_SHA=_head(repo)
    )
    assert r.returncode == 0
    assert r.stdout == "run=false\n"


def test_merge_group_with_empty_head_sha_defaults_to_checkout_head(repo):
    # The workflow always passes both, but an absent HEAD_SHA must fall back
    # to the checked-out merge commit, not fail open or fail closed.
    _commit(repo, "rtl/new.v", "x\n")
    r = _run(repo, EVENT_NAME="merge_group", BASE_SHA=_base(repo), HEAD_SHA="")
    assert r.returncode == 0
    assert r.stdout == "run=true\n"


@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
def test_other_events_run_everything(repo, event):
    r = _run(repo, EVENT_NAME=event)
    assert r.returncode == 0
    assert r.stdout == "run=true\n"


def test_pull_request_with_empty_base_fails_closed(repo):
    _commit(repo, "rtl/new.v", "x\n")
    r = _run(repo, EVENT_NAME="pull_request", BASE_REF="")
    assert r.returncode != 0
    assert r.stdout == ""
    assert "FAIL-CLOSED" in r.stderr


def test_pull_request_with_unresolvable_base_fails_closed(repo):
    # origin/nonesuch does not exist: the git diff itself fails. The inline
    # steps this replaces fed that failure to grep as "no match" and passed.
    _commit(repo, "rtl/new.v", "x\n")
    r = _run(repo, EVENT_NAME="pull_request", BASE_REF="nonesuch")
    assert r.returncode != 0
    assert r.stdout == ""
    assert "FAIL-CLOSED" in r.stderr


def test_merge_group_with_empty_base_fails_closed(repo):
    _commit(repo, "rtl/new.v", "x\n")
    r = _run(repo, EVENT_NAME="merge_group", BASE_SHA="", HEAD_SHA=_head(repo))
    assert r.returncode != 0
    assert r.stdout == ""
    assert "FAIL-CLOSED" in r.stderr


def test_merge_group_with_unresolvable_base_fails_closed(repo):
    _commit(repo, "rtl/new.v", "x\n")
    r = _run(
        repo,
        EVENT_NAME="merge_group",
        BASE_SHA="0123456789abcdef0123456789abcdef01234567",
        HEAD_SHA=_head(repo),
    )
    assert r.returncode != 0
    assert r.stdout == ""
    assert "FAIL-CLOSED" in r.stderr


def test_missing_path_regex_argument_fails(repo):
    r = subprocess.run(["sh", str(SCRIPT)], cwd=repo, capture_output=True, text=True)
    assert r.returncode != 0
    assert r.stdout == ""
