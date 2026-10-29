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
