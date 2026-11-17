"""Check the status tokens on the #N references in docs/roadmap.md.

docs/roadmap.md is hand-written and its status lines have gone stale within
hours of every refresh pass. The volatile part — whether each referenced
issue or PR is still open — is therefore carried by an explicit token on
every `#N` reference in the `## Now` and `## Next` sections: `#169 (open)`,
`#89 (closed)`, `PR #90 (merged)`. This checker fails when a reference in
those two sections carries no token, when a token contradicts the state
recorded in WORK_LOG.md (`**Issue #N** (closed)` / `**PR #N**` entries), or
when the state source itself is missing or has no entries.

Scope bound (deliberate): only `## Now` and `## Next` are checked. The
header, `## Where it stands` and its T1 table, `## Later`, `## Blocked and
waiting` and `## Not planned` may reference issues freely without tokens —
the same bound #181's AC3 drew for the manual re-check, not a widening of it.

One-sided soundness: WORK_LOG.md is append-only and maintained by the Guide
role, so it can lag the forge but never falsely records a closure or a
merge. "Claimed open but recorded closed/merged" is therefore a certain
roadmap error. "Claimed closed/merged but absent from WORK_LOG.md" can also
fire on Guide lag rather than a roadmap error; it is still reported, with
both fixes named in the message (correct the token, or update WORK_LOG.md
in this PR). "(closed)" means closed, not done: the work log does not
record why an issue closed, so the checker never reads closed as done.

    python3 verification/check_roadmap.py [roadmap.md [WORK_LOG.md]]

Stdlib only. Offline: no network, no gh, no subprocess. A doc-status lint;
it says nothing about the RTL.
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROADMAP = REPO_ROOT / "docs/roadmap.md"
DEFAULT_WORKLOG = REPO_ROOT / "WORK_LOG.md"
SECTIONS = ("Now", "Next")
ISSUE_CLOSED = re.compile(r"^\s*-\s*\*\*Issue #(\d+)\*\*\s+\(closed\)", re.M)
PR_MERGED = re.compile(r"^\s*-\s*\*\*PR #(\d+)\*\*:", re.M)
HEADING = re.compile(r"^## (.+)$", re.M)
REF = re.compile(
    r"\bPR #(?P<pr>\d+)(?P<pr_tok>\s*\((?:open|merged)\))?"
    r"|"
    r"#(?P<issue>\d+)(?P<issue_tok>\s*\((?:open|closed|merged)\))?"
)


def parse_state(worklog_path, errors):
    """Append to errors and return (closed_issues, merged_prs), or None."""
    try:
        text = Path(worklog_path).read_text()
    except OSError as e:
        errors.append(
            f"{worklog_path}: cannot read WORK_LOG.md ({e}) — the checker"
            " refuses to pass without its state source"
        )
        return None
    closed = {int(n) for n in ISSUE_CLOSED.findall(text)}
    merged = {int(n) for n in PR_MERGED.findall(text)}
    if not closed and not merged:
        errors.append(
            f"{worklog_path}: no '**Issue #N** (closed)' or '**PR #N**'"
            " entries found — WORK_LOG.md's format has changed?"
        )
        return None
    return closed, merged


def sections(text):
    """Return {heading name: body text} for the doc's ## sections."""
    headings = list(HEADING.finditer(text))
    return {
        m.group(1).strip(): text[
            m.end(): headings[i + 1].start() if i + 1 < len(headings) else len(text)
        ]
        for i, m in enumerate(headings)
    }


def check(roadmap_path=DEFAULT_ROADMAP, worklog_path=DEFAULT_WORKLOG):
    """Return a list of error strings (empty when every token agrees)."""
    errors = []
    try:
        text = Path(roadmap_path).read_text()
    except OSError as e:
        return [f"{roadmap_path}: cannot read the roadmap ({e})"]
    state = parse_state(worklog_path, errors)
    if state is None:
        return errors
    closed, merged = state
    spans = sections(text)
    missing = [name for name in SECTIONS if name not in spans]
    for name in missing:
        errors.append(f"{Path(roadmap_path).name}: no '## {name}' section")
    seen = 0
    for name in SECTIONS:
        body = spans.get(name)
        if body is None:
            continue
        for m in REF.finditer(body):
            seen += 1
            is_pr = m.group("pr") is not None
            num = int(m.group("pr") or m.group("issue"))
            tok = (
                m.group("pr_tok") if is_pr else m.group("issue_tok")
            ) or ""
            tok = tok.strip()
            kind = "PR" if is_pr else "issue"
            where = f"## {name} {kind} #{num}"
            if not tok:
                errors.append(
                    f"{where}: no status token — one of (open), (closed)"
                    " (issues), (merged) (PRs) is required"
                )
            elif tok[1:-1] == "open":
                if num in closed or num in merged:
                    state_word = "closed" if num in closed else "merged"
                    errors.append(
                        f"{where}: claimed open but WORK_LOG.md records it"
                        f" {state_word}"
                    )
            elif tok[1:-1] == "merged":
                if num not in merged:
                    detail = (
                        f"WORK_LOG.md records #{num} as a closed issue, not"
                        " a merged PR"
                        if num in closed
                        else "WORK_LOG.md does not record it"
                    )
                    errors.append(
                        f"{where}: claimed merged but {detail} — correct the"
                        " token, or update WORK_LOG.md in this PR"
                    )
            elif not recorded_closed(num, closed, merged):
                errors.append(
                    f"{where}: claimed closed but WORK_LOG.md does not"
                    " record it — correct the token, or update WORK_LOG.md"
                    " in this PR"
                )
    if not missing and seen == 0:
        errors.append(
            f"{Path(roadmap_path).name}: no '#N' references found in"
            f" {' / '.join('## ' + s for s in SECTIONS)} — parser drift?"
        )
    return errors


def recorded_closed(num, closed, merged):
    """A bare #N (closed) claim is met by a closed issue or a merged PR."""
    return num in closed or num in merged


def main(argv):
    roadmap = Path(argv[1]) if len(argv) > 1 else DEFAULT_ROADMAP
    worklog = Path(argv[2]) if len(argv) > 2 else DEFAULT_WORKLOG
    errors = check(roadmap, worklog)
    for e in errors:
        print(f"check_roadmap: {e}", file=sys.stderr)
    if not errors:
        print(f"check_roadmap: ok ({roadmap.name} vs {worklog.name})")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
