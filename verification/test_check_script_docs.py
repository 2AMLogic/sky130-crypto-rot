import json

from verification import check_script_docs

LINT = (
    "python3 -m compileall -q verification flow"
    " && python3 verification/check_pins.py"
    " && python3 verification/check_script_docs.py"
)
TEST = (
    "python3 -m pytest verification/model"
    " verification/test_check_pins.py"
    " verification/test_check_script_docs.py"
)

README_OK = """\
## What CI runs vs. what stays local

| Where | What |
|---|---|
| CI `lint` | `compileall`; `check_pins.py` (pins agree); `check_script_docs.py` (this table's inventory) |
| CI `model` | the pytest run: `test_check_pins.py` (pin resolution), `test_check_script_docs.py` (this table's inventory) |
| CI `reuse` | `check_reuse.py` re-hashes each `reuse.lock.json` file |
| CI `verify` | the benches |
"""


def _rows(readme=README_OK):
    text = readme
    return (
        check_script_docs.find_row(text, check_script_docs.LINT_ROW_LABEL),
        check_script_docs.find_row(text, check_script_docs.MODEL_ROW_LABEL),
    )


def test_matching_inventory_passes():
    lint_row, model_row = _rows()
    assert check_script_docs.check(LINT, TEST, lint_row, model_row) == []


def test_missing_lint_row_entry_fails():
    """A checker added to `lint` but not to the row is named by the error."""
    lint_row, model_row = _rows()
    errors = check_script_docs.check(
        LINT + " && python3 verification/check_roadmap.py", TEST, lint_row, model_row
    )
    assert len(errors) == 1
    assert "check_roadmap.py" in errors[0]
    assert "CI `lint`" in errors[0]


def test_missing_model_row_entry_fails():
    """The #229 drift: a self-test in `test` but absent from the model row."""
    lint_row, model_row = _rows()
    errors = check_script_docs.check(
        LINT,
        TEST + " verification/test_trng_if_record.py",
        lint_row,
        model_row,
    )
    assert len(errors) == 1
    assert "test_trng_if_record.py" in errors[0]
    assert "CI `model`" in errors[0]


def test_absent_row_fails():
    """A moved or deleted row must fail loudly, never pass vacuously."""
    lint_row, model_row = _rows()
    errors = check_script_docs.check(LINT, TEST, None, model_row)
    assert len(errors) == 1 and "no 'CI `lint`' row" in errors[0]
    errors = check_script_docs.check(LINT, TEST, lint_row, None)
    assert len(errors) == 1 and "no 'CI `model`' row" in errors[0]


def test_lint_row_without_checker_filename_fails():
    """A reworded row that names no checker at all trips the guard."""
    lint_row, model_row = _rows()
    reworded = lint_row.replace(
        "`check_pins.py` (pins agree); `check_script_docs.py` (this table's inventory)",
        "the pin check and the script-docs check",
    )
    errors = check_script_docs.check(LINT, TEST, reworded, model_row)
    assert len(errors) == 3
    assert any("names no checker filename" in e for e in errors)
    assert any("check_pins.py" in e for e in errors)
    assert any("check_script_docs.py" in e for e in errors)


def test_model_row_without_selftest_filename_fails():
    lint_row, model_row = _rows()
    reworded = model_row.replace(
        "`test_check_pins.py` (pin resolution), `test_check_script_docs.py`"
        " (this table's inventory)",
        "the pin and script-docs self-tests",
    )
    errors = check_script_docs.check(LINT, TEST, lint_row, reworded)
    assert len(errors) == 3
    assert any("names no self-test filename" in e for e in errors)
    assert any("test_check_pins.py" in e for e in errors)
    assert any("test_check_script_docs.py" in e for e in errors)


def test_checker_invoked_with_arguments_still_demanded():
    lint_row, model_row = _rows()
    lint = LINT + " && python3 verification/check_roadmap.py --strict"
    errors = check_script_docs.check(lint, TEST, lint_row, model_row)
    assert len(errors) == 1 and "check_roadmap.py" in errors[0]


def test_check_star_script_outside_lint_is_not_demanded():
    """check_reuse.py lives in check:reuse, not lint: never demanded here."""
    lint_row, model_row = _rows()
    assert "check_reuse.py" not in lint_row
    assert check_script_docs.check(LINT, TEST, lint_row, model_row) == []


def test_rows_found_by_label_cell_after_a_rewrite():
    """Rows above shift and wording changes: the label cell is the anchor."""
    readme = README_OK.replace(
        "## What CI runs vs. what stays local",
        "## What CI runs vs. what stays local\n\n| Where | What |\n|---|---|\n"
        "| CI `verify` | moved above the lint row on a rewrite |",
    )
    readme = readme.replace("(this table's inventory)", "(the script inventory)")
    lint_row, model_row = _rows(readme)
    assert check_script_docs.check(LINT, TEST, lint_row, model_row) == []


def test_name_inside_a_longer_name_is_not_a_match():
    """check_pins.py must not be satisfied by a row naming test_check_pins.py."""
    assert check_script_docs._name_in_text("test_check_pins.py", "check_pins.py") is False
    assert check_script_docs._name_in_text("`check_pins.py`", "check_pins.py") is True
    lint_row, model_row = _rows()
    # the model row names test_check_pins.py, which must not vouch for a
    # lint-row demand of check_pins.py on the lint row itself:
    assert check_script_docs._name_in_text(model_row, "check_pins.py") is False
    assert check_script_docs.check(LINT, TEST, lint_row, model_row) == []


def test_repo_inventory_agrees():
    """The real surfaces: package.json vs verification/README.md on this tree."""
    assert check_script_docs.main([]) == 0


def test_scripts_missing_in_package_json_demand_nothing():
    """An empty scripts block still guards the rows, but demands no names."""
    lint_row, model_row = _rows()
    assert check_script_docs.check("", "", lint_row, model_row) == []
