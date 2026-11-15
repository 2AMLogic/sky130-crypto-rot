"""The netlist OP_GEN binding indexes the probe pattern from the LSB end.

Issue #206: probe_opgen read the `$display("%b", ...)` op_q patterns left to
right as if position 0 were bit 0, but %b is MSB first, so the generated
conjunction named the wrong bits -- harmless only while the GEN pattern stayed
symmetric (0z0), loud (a net_prove FAIL in S_GEN_ISSUE) the day a
re-synthesis yields an asymmetric one. The binding must also be false for the
INST pattern now: the property text's `op_q != OP_GEN' is replaced by the
conjunction's negation, so a conjunction satisfied in more op states than
OP_GEN silently weakens the P-8 reseed term.

The full netlist flow is local-only (PDK, pinned yosys/sby/z3 -- see
verification/README.md), so this pins the generator's parsing and binding
contract directly, the way test_keyladder_formal_record.py pins `sby_depth`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GENERATOR = "verification/formal/gen_netlist.py"


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("formal_gen_netlist", REPO / GENERATOR)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["formal_gen_netlist"] = mod
    spec.loader.exec_module(mod)
    return mod


# --- parse_probe_patterns ---------------------------------------------------


def test_parse_reads_both_patterns_whole(gen):
    stdout = "OP_AFTER_INST=0z1\nOP_AFTER_GEN=0z0\n"
    assert gen.parse_probe_patterns(stdout, "", "clean") == ("0z1", "0z0")


def test_parse_keeps_a_wider_pattern_untruncated(gen):
    stdout = "OP_AFTER_INST=01z1\nOP_AFTER_GEN=0z01\n"
    assert gen.parse_probe_patterns(stdout, "", "clean") == ("01z1", "0z01")


def test_parse_dies_without_both_patterns(gen):
    with pytest.raises(SystemExit):
        gen.parse_probe_patterns("OP_AFTER_INST=0z1\nPROBE_FAIL\n", "", "clean")


# --- opgen_binding ----------------------------------------------------------


def test_binding_pins_the_recorded_conjunction(gen):
    # The clean netlist of record 20261115-084328-a801ec1 measured INST=0z1,
    # GEN=0z0 -- the symmetric case where the old and new indexing coincide.
    # Byte-identical to the conjunction spliced into the recorded proofs, so
    # the fix is observably a no-op at the current toolchain pin.
    assert gen.opgen_binding("0z1", "0z0", "clean") == \
        "(op_q[0] == 1'b0 && op_q[2] == 1'b0)"


def test_binding_indexes_from_the_lsb_end(gen):
    # GEN=10z: the leading '1' is bit 2, not bit 0. The old left-to-right
    # loop bound it to op_q[0]; the conjunction must name op_q[2]. Byte-exact,
    # so the old term order fails this too.
    assert gen.opgen_binding("0z1", "10z", "clean") == \
        "(op_q[1] == 1'b0 && op_q[2] == 1'b1)"


def test_binding_beyond_three_bits(gen):
    # A width the old {3} regex silently truncated: GEN=0z10 drives bits 0, 1
    # and 3; bit 2 reads z (optimized away) and stays out of the binding.
    assert gen.opgen_binding("1010", "0z10", "clean") == \
        "(op_q[0] == 1'b0 && op_q[1] == 1'b1 && op_q[3] == 1'b0)"


def test_binding_dies_when_inst_satisfies_it_too(gen, capsys):
    # GEN=0zz drives only bit 2 to 0; INST=01z also reads 0 there, so the
    # conjunction would hold in more op states than OP_GEN and weaken the
    # `op_q != OP_GEN' substitution feeding the P-8 reseed term.
    with pytest.raises(SystemExit):
        gen.opgen_binding("01z", "0zz", "clean")
    assert "too wide" in capsys.readouterr().err


def test_binding_dies_on_identical_patterns(gen, capsys):
    with pytest.raises(SystemExit):
        gen.opgen_binding("0z0", "0z0", "clean")
    assert "too wide" in capsys.readouterr().err


def test_binding_dies_on_unequal_widths_naming_both(gen, capsys):
    with pytest.raises(SystemExit):
        gen.opgen_binding("01", "0z0", "clean")
    err = capsys.readouterr().err
    assert "2 bits" in err and "3 bits" in err


def test_binding_dies_without_driven_bits(gen, capsys):
    with pytest.raises(SystemExit):
        gen.opgen_binding("0z1", "zzz", "clean")
    assert "no driven bits" in capsys.readouterr().err
