import copy
import json

from verification import check_pins

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


def test_agreeing_pins_pass(tmp_path):
    assert check_pins.check(*_write(tmp_path)) == []


def test_drifted_pin_fails(tmp_path):
    errors = check_pins.check(*_write(tmp_path, script=SCRIPT.replace("2.1.0", "2.2.0")))
    assert len(errors) == 1 and "COCOTB_VERSION" in errors[0]


def test_value_outside_section_does_not_count(tmp_path):
    errors = check_pins.check(*_write(tmp_path, script=SCRIPT.replace("2.1.0", "9.9.9")))
    assert len(errors) == 1


def test_missing_block_or_section_fails(tmp_path):
    assert check_pins.check(*_write(tmp_path, script="KLT_VERSION=\"0.8.0\"\n"))
    assert check_pins.check(*_write(tmp_path, doc="no table\n"))


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
    assert check_pins.check_inventory(*_write_inventory(tmp_path)) == []


def test_drifted_inventory_tool_pin_fails(tmp_path):
    """The real drift this check exists for: a stale klayout-tools git revision."""
    inv = copy.deepcopy(INVENTORY)
    inv["pins"]["tools"]["klayout-tools"] = "dac2b5daceb69a2068d9d2ee190d7afe37b29af7"
    errors = check_pins.check_inventory(*_write_inventory(tmp_path, inventory=inv))
    assert len(errors) == 1
    assert "pins.tools.klayout-tools" in errors[0] and "KLT_VERSION" in errors[0]


def test_drifted_inventory_pdk_revision_fails(tmp_path):
    inv = copy.deepcopy(INVENTORY)
    inv["pins"]["pdk"]["revision"] = "deadbeef"
    errors = check_pins.check_inventory(*_write_inventory(tmp_path, inventory=inv))
    assert len(errors) == 1
    assert "pins.pdk.revision" in errors[0] and "CIEL_SKY130_VERSION" in errors[0]


def test_missing_inventory_pin_fails(tmp_path):
    inv = copy.deepcopy(INVENTORY)
    del inv["pins"]["tools"]["cocotb"]
    errors = check_pins.check_inventory(*_write_inventory(tmp_path, inventory=inv))
    assert len(errors) == 1 and "is missing" in errors[0]


def test_icarus_verilog_is_not_checked(tmp_path):
    """It has no counterpart in the pin block, so a change there must not fail."""
    inv = copy.deepcopy(INVENTORY)
    inv["pins"]["tools"]["icarus-verilog"] = "12.0"
    assert check_pins.check_inventory(*_write_inventory(tmp_path, inventory=inv)) == []


def test_missing_pins_block_or_pin_block_fails(tmp_path):
    assert check_pins.check_inventory(*_write_inventory(tmp_path, inventory={}))
    assert check_pins.check_inventory(*_write_inventory(tmp_path, script="X=\"1\"\n"))


def test_pin_block_without_counterpart_constant_fails(tmp_path):
    """A pin block that drops a constant the inventory maps to is a failure."""
    script = FULL_SCRIPT.replace('CIEL_VERSION="2.6.1"\n', "")
    errors = check_pins.check_inventory(*_write_inventory(tmp_path, script=script))
    assert len(errors) == 1 and "no counterpart" in errors[0]
