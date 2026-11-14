"""Check that scripts/setup-env.sh's pins agree with the repo's hand copies.

Three copy sets are checked, all against the pin block of the script (between
the `# --- pinned versions` line and the closing `# ----` rule):

* **docs/environment.md** — every `NAME="value"` assignment in the block must
  have its value appear in the doc's "Pinned versions" section. A missing
  block, an empty block or a missing section fails.
* **manifests/inventories/item-9.json** — the `pins` block the T1 item-9
  attestation declares (and `klt signoff --attest 9` records into the
  envelope) must name the same versions: `pins.tools."klayout-tools"` vs
  `KLT_VERSION`, `pins.tools."yowasp-yosys"` vs `YOWASP_YOSYS_VERSION`,
  `pins.tools.cocotb` vs `COCOTB_VERSION`, `pins.tools.ciel` vs
  `CIEL_VERSION`, and `pins.pdk.revision` vs `CIEL_SKY130_VERSION`.
  `pins.tools."icarus-verilog"` is deliberately NOT checked: it has no
  counterpart in the pin block, because scripts/setup-env.sh only probes for
  Icarus as a host package and never pins it.

* **the klt version literals hand-copied into commands and prose** --
  `.github/workflows/signoff.yml`, `manifests/README.md` and `README.md`
  (`KLT_LITERAL_FILES`). Every `klayout-tools==<version>` literal and every
  backticked `` `v<version>` `` release tag in those files must equal
  `KLT_VERSION`. These are embedded in `pip`/`uvx` command lines and prose
  rather than in a structured block, so they are matched by regex
  (`KLT_LITERALS`) rather than mapped by key. A listed file that is missing,
  unreadable, or carries no literal at all fails: a checker that silently
  matches nothing after a rename is the drift this guards against.

    python3 verification/check_pins.py [setup-env.sh [environment.md [item-9.json]]]

Stdlib only. Checks that the files agree with each other; it does not check
the pins against what is installed or what upstream publishes.
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSIGN = re.compile(r'^([A-Z][A-Z0-9_]*)="([^"]*)"\s*$')

# (role, key) in the inventory's "pins" block -> constant in the pin block.
# "icarus-verilog" is absent on purpose; see the module docstring.
INVENTORY_PINS = {
    ("tools", "klayout-tools"): "KLT_VERSION",
    ("tools", "yowasp-yosys"): "YOWASP_YOSYS_VERSION",
    ("tools", "cocotb"): "COCOTB_VERSION",
    ("tools", "ciel"): "CIEL_VERSION",
    ("pdk", "revision"): "CIEL_SKY130_VERSION",
}

# Files carrying a hand copy of the klt pin in command or prose form, checked
# against KLT_VERSION. Resolved against REPO_ROOT by main().
#
# docs/environment.md is deliberately NOT here: check() already guards its
# "Pinned versions" table, and its changelog section names older versions on
# purpose (the `dac2b5da` -> PyPI move), so an equality rule would false-fail.
# scripts/setup-env.sh is not here either: its three `klayout-tools==${KLT_VERSION}`
# sites are interpolations of the source of truth, not hand copies. Generated
# artifacts (manifests/*.signoff.json, inventories/*.envelope.json,
# verification/records/**) are tool output already bound by the signoff job.
KLT_LITERAL_FILES = (
    ".github/workflows/signoff.yml",
    "manifests/README.md",
    "README.md",
)

# `klayout-tools==X` as written in a pip/uvx command line or inline code, and
# the backticked release tag `vX` the vendored tiers doc cites. The tag form
# requires two dotted components so that the `actions/checkout@v4` and
# `actions/setup-python@v5` refs in signoff.yml cannot match it.
KLT_LITERALS = (
    re.compile(r"""klayout-tools==([0-9][^\s"'`]*)"""),
    re.compile(r"`v([0-9]+\.[0-9]+[^`]*)`"),
)


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


def check_inventory(script_path, inventory_path):
    """Return a list of error strings (empty when the inventory's pins agree)."""
    pins = parse_pins(Path(script_path).read_text())
    if not pins:
        return [f"{script_path}: no pin block (or no assignments) found"]
    declared = json.loads(Path(inventory_path).read_text()).get("pins")
    if not declared:
        return [f"{inventory_path}: no 'pins' block"]
    errors = []
    for (role, key), name in INVENTORY_PINS.items():
        where = f"{inventory_path}: pins.{role}.{key}"
        if name not in pins:
            errors.append(f'{where} has no counterpart: {name} is not in {script_path}')
        elif key not in declared.get(role, {}):
            errors.append(f'{where} is missing (expected {name}="{pins[name]}")')
        elif declared[role][key] != pins[name]:
            errors.append(
                f'{where}="{declared[role][key]}" '
                f'disagrees with {name}="{pins[name]}" in {script_path}'
            )
    return errors


def check_literals(script_path, literal_paths):
    """Return a list of error strings (empty when every klt literal agrees)."""
    pins = parse_pins(Path(script_path).read_text())
    if not pins:
        return [f"{script_path}: no pin block (or no assignments) found"]
    if "KLT_VERSION" not in pins:
        return [f'{script_path}: pin block has no KLT_VERSION assignment']
    want = pins["KLT_VERSION"]
    errors = []
    for literal_path in literal_paths:
        path = Path(literal_path)
        try:
            text = path.read_text()
        except OSError as exc:
            errors.append(
                f"{path}: cannot be read ({exc.strerror}), so its klt literals "
                f'cannot be checked against KLT_VERSION="{want}" in {script_path}'
            )
            continue
        found = 0
        for pattern in KLT_LITERALS:
            for match in pattern.finditer(text):
                found += 1
                if match.group(1) != want:
                    line = text.count("\n", 0, match.start()) + 1
                    errors.append(
                        f'{path}:{line}: klt literal "{match.group(1)}" disagrees '
                        f'with KLT_VERSION="{want}" in {script_path}'
                    )
        if not found:
            errors.append(
                f"{path}: no klt version literal found (expected "
                f'KLT_VERSION="{want}"); has the file moved or its wording changed?'
            )
    return errors


def main(argv):
    script = Path(argv[1]) if len(argv) > 1 else REPO_ROOT / "scripts/setup-env.sh"
    doc = Path(argv[2]) if len(argv) > 2 else REPO_ROOT / "docs/environment.md"
    inventory = (
        Path(argv[3]) if len(argv) > 3
        else REPO_ROOT / "manifests/inventories/item-9.json"
    )
    literals = [REPO_ROOT / p for p in KLT_LITERAL_FILES]
    errors = (
        check(script, doc)
        + check_inventory(script, inventory)
        + check_literals(script, literals)
    )
    for e in errors:
        print(f"FAIL {e}")
    if errors:
        return 1
    # Repo-relative, not .name: manifests/README.md and README.md are distinct
    # files whose basenames collide.
    names = ", ".join(KLT_LITERAL_FILES)
    print(
        f"pins OK: {script.name} vs {doc.name} vs {inventory.name}; "
        f"klt literals OK in {names}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
