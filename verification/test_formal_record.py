"""The drbg-trng formal generator reads sby's depth the way every generator does.

Issue #221: verification/formal/make_record.py carried a second copy of
sby_depth() that still matched section headers on the raw line, so a
`[script]  # note` header read a later `depth 99` as the run's depth (99, where
sby ran 4) -- the defect issue #194 fixed only in the key-ladder generator's
copy. Both generators now use record_lib.sby_depth; this pins that this reader
agrees with the shared helper on cases A, B and C, so the contract cannot
silently diverge again. (The EXPECT judge is pinned separately in
test_drbg_trng_formal_record.py.)
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "flow/common"))
import record_lib  # noqa: E402

GENERATOR = "verification/formal/make_record.py"

CASES = {
    "A": ("[options]\nmode bmc\ndepth 4\n\n[script]\ndepth 99\n", 4),
    "B": ("[options]\nmode bmc\ndepth 4\n\n[script]  # note\ndepth 99\n", 4),
    "C": ("[options]\nmode bmc\ndepth 4\n\n[script]\nread_verilog t.v\n[options]  # trick\ndepth 99\n", 4),
}


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("formal_make_record_221", REPO / GENERATOR)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["formal_make_record_221"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_generator_uses_the_shared_reader_not_a_local_copy(gen):
    assert gen.sby_depth is record_lib.sby_depth


@pytest.mark.parametrize("case", sorted(CASES))
def test_generator_depth_matches_the_shared_helper(gen, tmp_path, case):
    config, expected = CASES[case]
    d = tmp_path / "p7_p8_prove"
    d.mkdir()
    (d / "config.sby").write_text(config)
    assert gen.sby_depth(d) == record_lib.sby_depth(d) == expected
