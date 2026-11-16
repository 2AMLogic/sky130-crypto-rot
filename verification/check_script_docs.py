"""Check that verification/README.md's CI rows name what package.json runs.

`package.json`'s `lint` and `test` scripts and the CI table in
verification/README.md both enumerate the repo's checkers and self-tests,
and nothing linked them: two consecutive checker additions (#198 by hand,
#227 not at all) drifted the table before this check existed (issue #229).
This checker derives the expected set from package.json at runtime and
asserts it against the table, so a PR that adds a checker to a script
without adding it to the table fails lint.

Two checked pairs:

* **`scripts.lint` -> the `CI lint` row** -- every `verification/check_*.py`
  invoked in the `lint` string must be named in the row. Scoped to the
  `lint` string only: `check_reuse.py` lives in the separate `check:reuse`
  script and belongs to the `CI reuse` row, so it is deliberately not
  demanded here. A checker invoked with trailing arguments still counts:
  the match binds to the path token, not the whole command.
* **`scripts.test` -> the `CI model` row** -- every `verification/test_*.py`
  in the `test` string must be named in the row.

`README.md`'s Reproduce block is deliberately NOT checked: its glosses are
prose ("pin check", not `check_pins.py`), and it now points at the table
instead of enumerating (issue #229). This table is the one surface where a
filename-containment assertion can be made without destroying what the
line is for.

Anti-silent-match guard (carried over from check_pins.py): a row that
cannot be located, or that is located but names no filename of its kind,
fails -- a checker that silently matches nothing after a rename is the
drift this guards against. Rows are located by their `| CI lint |` /
`| CI model |` label cell, not by line number, so edits elsewhere in the
table cannot misalign the check. A name counts as present only when it is
not the tail of a longer one (`check_pins.py` does not match inside
`test_check_pins.py`).

    python3 verification/check_script_docs.py [package.json [verification/README.md]]

Stdlib only. Checks that the two surfaces agree; it does not run anything
they name.
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

LINT_ROW_LABEL = "CI `lint`"
MODEL_ROW_LABEL = "CI `model`"

# The invocation forms the scripts use. A checker invoked with trailing
# arguments still matches: the regex binds to the path token, not the command.
CHECK_INVOCATION = re.compile(r"verification/check_[A-Za-z0-9_]+\.py")
TEST_INVOCATION = re.compile(r"verification/test_[A-Za-z0-9_]+\.py")

# What "carries a filename" means for each row kind; the lookbehind keeps a
# `test_*.py` name from counting as a `check_*.py` hit and vice versa. A row
# that names none of its kind fails even when the expected set is empty: the
# guard exists to catch renames, not just omissions.
LINT_ROW_FILENAME = re.compile(r"(?<![\w])check_[A-Za-z0-9_]+\.py")
MODEL_ROW_FILENAME = re.compile(r"(?<![\w])test_[A-Za-z0-9_]+\.py")


def lint_checkers(lint_script):
    """Basenames of the check_*.py files the `lint` string invokes, sorted."""
    return sorted(
        {m.group().rsplit("/", 1)[-1] for m in CHECK_INVOCATION.finditer(lint_script)}
    )


def test_files(test_script):
    """Basenames of the test_*.py files the `test` string runs, sorted."""
    return sorted(
        {m.group().rsplit("/", 1)[-1] for m in TEST_INVOCATION.finditer(test_script)}
    )


def _name_in_text(text, basename):
    """True when basename appears in text not as the tail of a longer name."""
    return re.search(r"(?<![\w])" + re.escape(basename), text) is not None


def find_row(readme_text, label):
    """Return the table row line whose first cell is label, or None."""
    pattern = re.compile(r"\|\s*" + re.escape(label) + r"\s*\|")
    for line in readme_text.splitlines():
        if pattern.match(line):
            return line
    return None


def check(lint_script, test_script, lint_row, model_row):
    """Return a list of error strings (empty when the rows agree)."""
    errors = []
    for label, row, expected, kind_re, kind in (
        (LINT_ROW_LABEL, lint_row, lint_checkers(lint_script), LINT_ROW_FILENAME, "checker"),
        (MODEL_ROW_LABEL, model_row, test_files(test_script), MODEL_ROW_FILENAME, "self-test"),
    ):
        if row is None:
            errors.append(
                f"verification/README.md: no '{label}' row found, so the "
                f"npm-script inventory cannot be checked against it"
            )
            continue
        if not kind_re.search(row):
            errors.append(
                f"verification/README.md: the '{label}' row names no {kind} "
                f"filename; has the table been reworded? (a row that matches "
                f"nothing is the drift this checker guards against)"
            )
        for name in expected:
            if not _name_in_text(row, name):
                errors.append(
                    f"verification/README.md: the '{label}' row does not name "
                    f"{name}, which package.json runs"
                )
    return errors


def main(argv):
    package_json = Path(argv[1]) if len(argv) > 1 else REPO_ROOT / "package.json"
    readme = (
        Path(argv[2]) if len(argv) > 2
        else REPO_ROOT / "verification/README.md"
    )
    scripts = json.loads(package_json.read_text()).get("scripts", {})
    text = readme.read_text()
    errors = check(
        scripts.get("lint", ""),
        scripts.get("test", ""),
        find_row(text, LINT_ROW_LABEL),
        find_row(text, MODEL_ROW_LABEL),
    )
    for e in errors:
        print(f"FAIL {e}")
    if errors:
        return 1
    print(
        "script docs OK: package.json lint/test inventory vs "
        "verification/README.md CI lint/model rows"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
