import json

import pytest

from .ctr_drbg import CtrDrbg
from .vectorlib import VECTOR_DIR, check_provenance, count_cavp_drbg_records, parse_cavp_drbg

NAME = "CTR_DRBG_pr_false.rsp"
SUPPORTED = {
    "AES-128 use df": (True, 128),
    "AES-128 no df": (False, 128),
    "AES-256 use df": (True, 256),
    "AES-256 no df": (False, 256),
}


def _sidecar():
    return json.loads((VECTOR_DIR / (NAME + ".source.json")).read_text())


def test_provenance():
    check_provenance(NAME)


def test_unsupported_sections_listed():
    path = check_provenance(NAME)
    sections = {r["section"] for r in parse_cavp_drbg(path)}
    assert sections == set(SUPPORTED) | set(_sidecar()["unsupported_sections"])


def test_vectors():
    path = check_provenance(NAME)
    records = parse_cavp_drbg(path)
    assert len(records) == count_cavp_drbg_records(path) > 0
    unsupported = _sidecar()["unsupported_sections"]
    run = skipped = 0
    for r in records:
        if r["section"] in unsupported:
            skipped += 1
            continue
        use_df, key_bits = SUPPORTED[r["section"]]
        drbg = CtrDrbg(use_df=use_df, key_bits=key_bits, reseed_interval=1 << 16)
        drbg.instantiate(r["EntropyInput"], r["Nonce"], r["PersonalizationString"])
        drbg.reseed(r["EntropyInputReseed"], r["AdditionalInputReseed"])
        drbg.generate(len(r["ReturnedBits"]), r["additional"][0])
        out = drbg.generate(len(r["ReturnedBits"]), r["additional"][1])
        assert out == r["ReturnedBits"], f"{r['section']} record {run + skipped}"
        run += 1
    assert run + skipped == len(records)
    assert run > 0 and skipped > 0


def _new(interval=3):
    return CtrDrbg(use_df=True, key_bits=128, reseed_interval=interval)


def test_parameters_have_no_defaults():
    with pytest.raises(TypeError):
        CtrDrbg()
    with pytest.raises(TypeError):
        CtrDrbg(use_df=True, key_bits=128)


def test_no_output_before_instantiate():
    drbg = _new()
    with pytest.raises(RuntimeError):
        drbg.generate(16)
    with pytest.raises(RuntimeError):
        drbg.reseed(bytes(32))


def test_reseed_interval_enforced():
    drbg = _new(interval=3)
    drbg.instantiate(bytes(32), bytes(16))
    for _ in range(3):
        drbg.generate(16)
    with pytest.raises(RuntimeError):
        drbg.generate(16)
    drbg.reseed(bytes(32))
    drbg.generate(16)
