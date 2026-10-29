"""Check that scripts/setup-env.sh's pins appear in docs/environment.md.

Every `NAME="value"` assignment in the pin block of the script (between the
`# --- pinned versions` line and the closing `# ----` rule) must have its
value appear in the "Pinned versions" section of the doc. A missing block,
an empty block or a missing section fails.

    python3 verification/check_pins.py [setup-env.sh [environment.md]]

Stdlib only. Checks that the two files agree; it does not check the pins
against what is installed or what upstream publishes.
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSIGN = re.compile(r'^([A-Z][A-Z0-9_]*)="([^"]*)"\s*$')


def parse_pins(script_text):
    """Return {NAME: value} from the pin block, or None if the block is absent."""
    pins, in_block = {}, False
    for line in script_text.splitlines():
        if line.startswith("# --- pinned versions"):
            in_block = True
        elif in_block and line.startswith("# ----"):
            return pins
        elif in_block:
            m = ASSIGN.match(line)
            if m:
                pins[m.group(1)] = m.group(2)
    return None


def pinned_section(doc_text):
    """Return the text of the "## Pinned versions" section, or None."""
    m = re.search(r"^## Pinned versions\s*$(.*?)(?=^## |\Z)", doc_text, re.S | re.M)
    return m.group(1) if m else None


def check(script_path, doc_path):
    """Return a list of error strings (empty when the pins agree)."""
    pins = parse_pins(Path(script_path).read_text())
    if not pins:
        return [f"{script_path}: no pin block (or no assignments) found"]
    section = pinned_section(Path(doc_path).read_text())
    if section is None:
        return [f"{doc_path}: no '## Pinned versions' section"]
    return [
        f'{name}="{value}" is not in the "Pinned versions" table of {doc_path}'
        for name, value in pins.items()
        if value not in section
    ]


def main(argv):
    script = Path(argv[1]) if len(argv) > 1 else REPO_ROOT / "scripts/setup-env.sh"
    doc = Path(argv[2]) if len(argv) > 2 else REPO_ROOT / "docs/environment.md"
    errors = check(script, doc)
    for e in errors:
        print(f"FAIL {e}")
    if errors:
        return 1
    print(f"pins OK: {script.name} vs {doc.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
