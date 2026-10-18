import json

import pytest

from . import kdf_ctr_hmac_sha256
from .vectorlib import (
    VECTOR_DIR,
    check_provenance,
    count_cavp_kbkdf_records,
    parse_cavp_kbkdf,
)

NAME = "KDFCTR_gen.rsp"
SUPPORTED_PRF = "HMAC_SHA256"


def _derive(loc, rlen, f):
    """Map one CAVP record onto the model's before/after parameters."""
    if loc == "BEFORE_FIXED":
        before, after = b"", bytes.fromhex(f["FixedInputData"])
    elif loc == "AFTER_FIXED":
        before, after = bytes.fromhex(f["FixedInputData"]), b""
    elif loc == "MIDDLE_FIXED":
        before = bytes.fromhex(f["DataBeforeCtrData"])
        after = bytes.fromhex(f["DataAfterCtrData"])
    else:
        raise AssertionError(f"unknown counter location {loc}")
    return kdf_ctr_hmac_sha256(
        bytes.fromhex(f["KI"]),
        counter_bits=rlen,
        out_bits=int(f["L"]),
        before=before,
        after=after,
    )


def test_provenance():
    check_provenance(NAME)


def test_vectors():
    path = check_provenance(NAME)
    sidecar = json.loads((VECTOR_DIR / (NAME + ".source.json")).read_text())
    records = parse_cavp_kbkdf(path)
    independent = count_cavp_kbkdf_records(path)
    assert len(records) == sum(independent.values())

    # Unsupported sections are recorded in the sidecar, not silently dropped.
    unsupported = {k: v for k, v in independent.items() if k != SUPPORTED_PRF}
    assert sidecar["unsupported_prfs"]["records_per_prf"] == unsupported
    assert sidecar["supported_sections"]["records"] == independent[SUPPORTED_PRF]

    run = 0
    for prf, loc, rlen, f in records:
        if prf != SUPPORTED_PRF:
            continue
        assert _derive(loc, rlen, f) == bytes.fromhex(f["KO"]), (loc, rlen, f)
        run += 1
    assert run == independent[SUPPORTED_PRF] > 0


def test_corrupted_vector_fails():
    path = check_provenance(NAME)
    prf, loc, rlen, f = next(r for r in parse_cavp_kbkdf(path) if r[0] == SUPPORTED_PRF)
    flipped = dict(f, KO=f["KO"][:-1] + ("0" if f["KO"][-1] != "0" else "1"))
    assert _derive(loc, rlen, f) == bytes.fromhex(f["KO"])
    assert _derive(loc, rlen, flipped) != bytes.fromhex(flipped["KO"])


def test_multi_iteration_truncation():
    # L = 320 needs two HMAC blocks; the result is the leftmost 320 bits.
    kw = dict(counter_bits=32, before=b"", after=b"x")
    long = kdf_ctr_hmac_sha256(b"k", out_bits=512, **kw)
    assert kdf_ctr_hmac_sha256(b"k", out_bits=320, **kw) == long[:40]


@pytest.mark.parametrize("kw", [
    dict(counter_bits=12, out_bits=256),
    dict(counter_bits=8, out_bits=12),
    dict(counter_bits=8, out_bits=256 * 256),
])
def test_rejects_bad_parameters(kw):
    with pytest.raises(ValueError):
        kdf_ctr_hmac_sha256(b"k", before=b"", after=b"", **kw)


def test_no_default_layout():
    with pytest.raises(TypeError):
        kdf_ctr_hmac_sha256(b"k")
