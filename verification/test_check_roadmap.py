from verification import check_roadmap

ROADMAP = """# Roadmap

The tracker is [#3](https://github.com/example/repo/issues/3).

## Where it stands

- The T1 table cites #47 and #88 with no tokens; this section is out of scope.

## Now

1. **First item** ({i89}) — done ({pr90}). {i87a} is unblocked.
2. **Second item** ({i169}) — the line that drifted.

## Next

- **Top level** ({i87b}) after {i89b}. Closes {i46}.
- **Routed GDS** ({i47}).

## Later

- **P-13** (#46) stays untokenized here.

## Not planned

- Nothing cites a checked ref.
"""
WORKLOG = """# Work Log

- **Issue #89** (closed): registered the map
- **Issue #169** (closed): the drift case
- **PR #90**: merged the map
"""
TOKENS = {
    "i89": "#89 (closed)",
    "i89b": "#89 (closed)",
    "pr90": "PR #90 (merged)",
    "i87a": "#87 (open)",
    "i87b": "#87 (open)",
    "i169": "#169 (closed)",
    "i46": "#46 (open)",
    "i47": "#47 (open)",
}


def _run(tmp_path, tokens=None, roadmap=ROADMAP, worklog=WORKLOG):
    toks = {**TOKENS, **(tokens or {})}
    rm = tmp_path / "roadmap.md"
    rm.write_text(roadmap.format(**toks))
    wl = tmp_path / "WORK_LOG.md"
    wl.write_text(worklog)
    return check_roadmap.check(rm, wl)


def test_consistent_tokens_pass(tmp_path):
    assert _run(tmp_path) == []


def test_open_claim_recorded_closed_fails(tmp_path):
    errs = _run(tmp_path, {"i169": "#169 (open)"})
    assert any("#169" in e and "claimed open" in e and "closed" in e for e in errs)


def test_closed_claim_not_recorded_names_both_fixes(tmp_path):
    errs = _run(tmp_path, {"i47": "#47 (closed)"})
    assert any(
        "#47" in e
        and "does not record" in e
        and "correct the token" in e
        and "update WORK_LOG.md" in e
        for e in errs
    )


def test_merged_claim_absent_from_worklog_fails(tmp_path):
    errs = _run(tmp_path, worklog="- **Issue #89** (closed): x\n")
    assert any(
        "PR #90" in e
        and "claimed merged" in e
        and "does not record" in e
        and "correct the token" in e
        for e in errs
    )


def test_missing_token_fails(tmp_path):
    errs = _run(tmp_path, {"i47": "#47"})
    assert any("#47" in e and "no status token" in e for e in errs)


def test_pr_open_claim_recorded_merged_fails(tmp_path):
    errs = _run(tmp_path, {"pr90": "PR #90 (open)"})
    assert any("PR #90" in e and "claimed open" in e and "merged" in e for e in errs)


def test_pr_closed_spelling_gets_merged_hint(tmp_path):
    errs = _run(tmp_path, {"pr90": "PR #90 (closed)"})
    assert any("PR #90" in e and "no status token" in e and "(merged)" in e for e in errs)


def test_bare_number_resolves_merged_pr(tmp_path):
    assert _run(tmp_path, {"pr90": "#90 (merged)"}) == []


def test_bare_number_open_claim_vs_merged_pr_fails(tmp_path):
    errs = _run(tmp_path, {"pr90": "#90 (open)"})
    assert any("#90" in e and "claimed open" in e and "merged" in e for e in errs)


def test_merged_claim_for_issue_closed_number_fails(tmp_path):
    errs = _run(tmp_path, {"i89": "#89 (merged)"})
    assert any("#89" in e and "closed issue, not a merged PR" in e for e in errs)


def test_disagreeing_tokens_across_sections_fail(tmp_path):
    errs = _run(tmp_path, {"i87b": "#87 (closed)"})
    assert any("#87" in e and "does not record" in e for e in errs)


def test_out_of_scope_refs_are_ignored(tmp_path):
    assert _run(tmp_path) == []


def test_missing_section_fails(tmp_path):
    rm = tmp_path / "roadmap.md"
    rm.write_text("# Roadmap\n\n## Now\n\n1. **Only** (#89 (closed)).\n")
    wl = tmp_path / "WORK_LOG.md"
    wl.write_text(WORKLOG)
    errs = check_roadmap.check(rm, wl)
    assert any("'## Next'" in e for e in errs)


def test_no_refs_in_scoped_sections_fails(tmp_path):
    rm = tmp_path / "roadmap.md"
    rm.write_text("# Roadmap\n\n## Now\n\nNothing.\n\n## Next\n\nNothing.\n")
    wl = tmp_path / "WORK_LOG.md"
    wl.write_text(WORKLOG)
    errs = check_roadmap.check(rm, wl)
    assert any("no '#N' references" in e for e in errs)


def test_missing_worklog_fails_clearly(tmp_path):
    rm = tmp_path / "roadmap.md"
    rm.write_text(ROADMAP.format(**TOKENS))
    errs = check_roadmap.check(rm, tmp_path / "absent.md")
    assert errs and "cannot read WORK_LOG.md" in errs[0]


def test_worklog_without_entries_fails(tmp_path):
    rm = tmp_path / "roadmap.md"
    rm.write_text(ROADMAP.format(**TOKENS))
    wl = tmp_path / "WORK_LOG.md"
    wl.write_text("# Work Log\n\n### 2026-01-01\n\n- nothing applicable\n")
    errs = check_roadmap.check(rm, wl)
    assert errs and "no '**Issue #N** (closed)'" in errs[0]


def test_missing_roadmap_fails(tmp_path):
    errs = check_roadmap.check(tmp_path / "absent.md", tmp_path / "WORK_LOG.md")
    assert errs and "cannot read the roadmap" in errs[0]


def test_real_tree_is_consistent():
    assert check_roadmap.check() == []
