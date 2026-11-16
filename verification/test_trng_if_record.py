"""The trng_if record names the flag that actually skipped a sibling bench.

Issue #202: make_record.py derived the reproduce command's skip flag from
`runs["real-full"]` alone, so a record written after `run.sh --record
--skip-real` claimed `--record --skip-real-full` -- a command that would in
fact run the unshortened bench the record says did not run. `--skip-real`
suppresses BOTH sibling benches (run.sh gates the unshortened pass on
`REAL=1 && REAL_FULL=1`), so the record must name the stronger flag.

The full generator only runs against a completed flow directory and the
append-only records tree, so this pins the `run_cmd` helper directly, the
way test_keyladder_formal_record.py pins `sby_depth`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GENERATOR = "verification/rtl/trng_if/make_record.py"

# What a bench's JSON looks like when it ran and passed; run_cmd only reads
# presence (truthiness), never a field of it.
RAN = {"status": "pass", "passed_count": 1, "test_count": 1}


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("trng_if_make_record", REPO / GENERATOR)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["trng_if_make_record"] = mod
    spec.loader.exec_module(mod)
    return mod


def _runs(real, real_full):
    """The runs dict make_record.main builds: the run's JSON when it executed,
    None when its bench was skipped."""
    return {"if": RAN, "sys": RAN, "real": real, "real-full": real_full}


def test_a_full_run_states_a_bare_record(gen):
    assert gen.run_cmd(_runs(RAN, RAN)) == "./verification/rtl/trng_if/run.sh --record"


def test_skip_real_full_names_skip_real_full(gen):
    assert gen.run_cmd(_runs(RAN, None)) == \
        "./verification/rtl/trng_if/run.sh --record --skip-real-full"


def test_skip_real_names_skip_real_not_skip_real_full(gen):
    """--skip-real suppresses both sibling benches, so the record must name
    --skip-real: --skip-real-full would re-run the bench the record omits."""
    assert gen.run_cmd(_runs(None, None)) == \
        "./verification/rtl/trng_if/run.sh --record --skip-real"


def test_both_flags_still_names_skip_real(gen):
    """Both flags on one command line is the stronger skip, not a contradictory
    pair: from the record's point of view it is the same skipped runs dict."""
    assert gen.run_cmd(_runs(None, None)) == \
        "./verification/rtl/trng_if/run.sh --record --skip-real"
