import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "flow/common"))
import record_lib  # noqa: E402

from verification import check_pins  # noqa: E402

SCRIPT = """\
# --- pinned versions -- keep in sync with docs/environment.md ----
KLT_VERSION="0.8.0"
# a comment
COCOTB_VERSION="2.1.0"
# -----------------------------------------------------------------
OTHER="ignored"
"""
DOC = """\
## Pinned versions

| klt | 0.8.0 |
| cocotb | 2.1.0 |

## Other

9.9.9
"""


def _write(tmp_path, script=SCRIPT, doc=DOC):
    s, d = tmp_path / "setup-env.sh", tmp_path / "environment.md"
    s.write_text(script)
    d.write_text(doc)
    return s, d


def _pins(s):
    """The parsed pin block of a script file this module wrote."""
    return record_lib.parse_pins(Path(s).read_text())


def test_agreeing_pins_pass(tmp_path):
    s, d = _write(tmp_path)
    assert check_pins.check(_pins(s), s, d) == []


def test_drifted_pin_fails(tmp_path):
    s, d = _write(tmp_path, script=SCRIPT.replace("2.1.0", "2.2.0"))
    errors = check_pins.check(_pins(s), s, d)
    assert len(errors) == 1 and "COCOTB_VERSION" in errors[0]


def test_value_outside_section_does_not_count(tmp_path):
    s, d = _write(tmp_path, script=SCRIPT.replace("2.1.0", "9.9.9"))
    errors = check_pins.check(_pins(s), s, d)
    assert len(errors) == 1


def test_missing_doc_section_fails(tmp_path):
    s, d = _write(tmp_path, doc="no table\n")
    assert check_pins.check(_pins(s), s, d)


def test_missing_pin_block_fails_once_in_main(tmp_path, capsys):
    """One parse, one guard (issue #189): a script with no pin block is a
    single FAIL line from main(), not one per checker."""
    s = tmp_path / "setup-env.sh"
    s.write_text('KLT_VERSION="0.8.0"\n')
    d = tmp_path / "environment.md"
    d.write_text(DOC)
    i = tmp_path / "item-9.json"
    i.write_text(json.dumps(INVENTORY))
    assert check_pins.main([str(s), str(d), str(i)]) == 1
    out = capsys.readouterr().out
    assert "no pin block" in out and out.count("FAIL") == 1


INVENTORY = {
    "pins": {
        "pdk": {"name": "sky130A", "revision": "f6eeac7d"},
        "tools": {
            "klayout-tools": "0.8.0",
            "yowasp-yosys": "0.68.0.0.post1208",
            "icarus-verilog": "13.0",
            "cocotb": "2.1.0",
            "ciel": "2.6.1",
        },
    }
}
FULL_SCRIPT = """\
# --- pinned versions -- keep in sync with docs/environment.md ----
KLT_VERSION="0.8.0"
CIEL_VERSION="2.6.1"
COCOTB_VERSION="2.1.0"
CIEL_SKY130_VERSION="f6eeac7d"
YOWASP_YOSYS_VERSION="0.68.0.0.post1208"
# -----------------------------------------------------------------
"""


def _write_inventory(tmp_path, script=FULL_SCRIPT, inventory=INVENTORY):
    s, i = tmp_path / "setup-env.sh", tmp_path / "item-9.json"
    s.write_text(script)
    i.write_text(json.dumps(copy.deepcopy(inventory)))
    return s, i


def test_agreeing_inventory_pins_pass(tmp_path):
    s, i = _write_inventory(tmp_path)
    assert check_pins.check_inventory(_pins(s), s, i) == []


def test_drifted_inventory_tool_pin_fails(tmp_path):
    """The real drift this check exists for: a stale klayout-tools git revision."""
    inv = copy.deepcopy(INVENTORY)
    inv["pins"]["tools"]["klayout-tools"] = "dac2b5daceb69a2068d9d2ee190d7afe37b29af7"
    s, i = _write_inventory(tmp_path, inventory=inv)
    errors = check_pins.check_inventory(_pins(s), s, i)
    assert len(errors) == 1
    assert "pins.tools.klayout-tools" in errors[0] and "KLT_VERSION" in errors[0]


def test_drifted_inventory_pdk_revision_fails(tmp_path):
    inv = copy.deepcopy(INVENTORY)
    inv["pins"]["pdk"]["revision"] = "deadbeef"
    s, i = _write_inventory(tmp_path, inventory=inv)
    errors = check_pins.check_inventory(_pins(s), s, i)
    assert len(errors) == 1
    assert "pins.pdk.revision" in errors[0] and "CIEL_SKY130_VERSION" in errors[0]


def test_missing_inventory_pin_fails(tmp_path):
    inv = copy.deepcopy(INVENTORY)
    del inv["pins"]["tools"]["cocotb"]
    s, i = _write_inventory(tmp_path, inventory=inv)
    errors = check_pins.check_inventory(_pins(s), s, i)
    assert len(errors) == 1 and "is missing" in errors[0]


def test_icarus_verilog_is_not_checked(tmp_path):
    """It has no counterpart in the pin block, so a change there must not fail."""
    inv = copy.deepcopy(INVENTORY)
    inv["pins"]["tools"]["icarus-verilog"] = "12.0"
    s, i = _write_inventory(tmp_path, inventory=inv)
    assert check_pins.check_inventory(_pins(s), s, i) == []


def test_missing_inventory_pins_block_fails(tmp_path):
    s, i = _write_inventory(tmp_path, inventory={})
    assert check_pins.check_inventory(_pins(s), s, i)


def test_pin_block_without_counterpart_constant_fails(tmp_path):
    """A pin block that drops a constant the inventory maps to is a failure."""
    s, i = _write_inventory(tmp_path, script=FULL_SCRIPT.replace('CIEL_VERSION="2.6.1"\n', ""))
    errors = check_pins.check_inventory(_pins(s), s, i)
    assert len(errors) == 1 and "no counterpart" in errors[0]


# The two literal forms as they really appear: `klayout-tools==X` in a pip or
# uvx command line, and the backticked release tag the vendored tiers doc cites.
WORKFLOW = """\
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        run: |
          pip install klayout-tools==0.8.0
"""
MANIFESTS_DOC = """\
  `docs/design-evidence-tiers.md` (the commit tag `v0.8.0` points to,
  2026-10-27; upstream is MIT-licensed).

`klayout-tools==0.8.0` (the first release with `klt signoff --attest`).

uvx --from "klayout-tools==0.8.0" klt signoff \\
"""


def _write_literals(tmp_path, script=FULL_SCRIPT, workflow=WORKFLOW, doc=MANIFESTS_DOC):
    s = tmp_path / "setup-env.sh"
    w = tmp_path / "signoff.yml"
    d = tmp_path / "manifests-README.md"
    s.write_text(script)
    w.write_text(workflow)
    d.write_text(doc)
    return s, [w, d]


def test_agreeing_literals_pass(tmp_path):
    s, paths = _write_literals(tmp_path)
    assert check_pins.check_literals(_pins(s), s, paths) == []


def test_drifted_literal_fails_and_names_its_file(tmp_path):
    """The real drift this check exists for: a KLT_VERSION bump that misses CI."""
    s, paths = _write_literals(tmp_path, workflow=WORKFLOW.replace("0.8.0", "0.9.0"))
    errors = check_pins.check_literals(_pins(s), s, paths)
    assert len(errors) == 1
    assert "signoff.yml" in errors[0]
    assert '"0.9.0"' in errors[0] and 'KLT_VERSION="0.8.0"' in errors[0]


def test_second_literal_file_fails_independently(tmp_path):
    """A drifted literal in one listed file must not mask or depend on another."""
    s, paths = _write_literals(
        tmp_path, doc=MANIFESTS_DOC.replace('"klayout-tools==0.8.0"', '"klayout-tools==0.9.0"')
    )
    errors = check_pins.check_literals(_pins(s), s, paths)
    assert len(errors) == 1
    assert "manifests-README.md" in errors[0] and '"0.9.0"' in errors[0]


def test_drifted_tag_literal_fails_independently_of_the_equals_form(tmp_path):
    """manifests/README.md:31's release tag moves with the pin; `==` sites agree."""
    s, paths = _write_literals(
        tmp_path, doc=MANIFESTS_DOC.replace("`v0.8.0`", "`v0.9.0`")
    )
    errors = check_pins.check_literals(_pins(s), s, paths)
    assert len(errors) == 1
    assert "manifests-README.md" in errors[0] and '"0.9.0"' in errors[0]


def test_action_refs_do_not_match_the_tag_pattern(tmp_path):
    """`actions/checkout@v4` is single-component and unbackticked: not a klt tag."""
    workflow = WORKFLOW.replace("klayout-tools==0.8.0", "klayout-tools==0.8.0  # `v4`")
    s, paths = _write_literals(tmp_path, workflow=workflow)
    assert check_pins.check_literals(_pins(s), s, paths) == []


def test_zero_match_listed_file_fails(tmp_path):
    """A file present but carrying no literal is a FAIL, never a silent pass."""
    s, paths = _write_literals(tmp_path, workflow="      - uses: actions/checkout@v4\n")
    errors = check_pins.check_literals(_pins(s), s, paths)
    assert len(errors) == 1 and "no klt version literal found" in errors[0]


def test_missing_listed_file_fails(tmp_path):
    """A renamed-away file must fail rather than quietly matching nothing."""
    s, paths = _write_literals(tmp_path)
    paths[0].unlink()
    errors = check_pins.check_literals(_pins(s), s, paths)
    assert len(errors) == 1 and "cannot be read" in errors[0]


def test_pin_block_without_klt_version_fails(tmp_path):
    s, paths = _write_literals(
        tmp_path, script=FULL_SCRIPT.replace('KLT_VERSION="0.8.0"\n', "")
    )
    errors = check_pins.check_literals(_pins(s), s, paths)
    assert len(errors) == 1 and "KLT_VERSION" in errors[0]
