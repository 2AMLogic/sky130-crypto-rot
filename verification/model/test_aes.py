import pytest

from . import aes
from .vectorlib import check_provenance, count_fips197_records, parse_fips197

NAME = "fips197.txt"


def test_provenance():
    check_provenance(NAME)


def test_vectors():
    path = check_provenance(NAME)
    vectors = parse_fips197(path)
    run = 0
    for section, v in vectors:
        key, pt, ct = v["KEY"], v["PLAINTEXT"], v["CIPHERTEXT"]
        assert aes.encrypt_block(key, pt) == ct, section
        assert aes.decrypt_block(key, ct) == pt, section
        rks = aes.round_keys(key)
        listed = {int(f[len("ROUNDKEY"):]): b for f, b in v.items() if f.startswith("ROUNDKEY")}
        assert listed
        for r, expected in listed.items():
            assert rks[r] == expected, f"{section} round key {r}"
        run += 1
    assert run == len(vectors) == count_fips197_records(path) == 2
    # Appendix A.1 lists all eleven AES-128 round keys.
    assert sum(1 for f in vectors[0][1] if f.startswith("ROUNDKEY")) == 11


def test_round_trip_on_vectors():
    for _, v in parse_fips197(check_provenance(NAME)):
        assert aes.decrypt_block(v["KEY"], aes.encrypt_block(v["KEY"], v["PLAINTEXT"])) == v["PLAINTEXT"]


def test_sbox_spot_values():
    # FIPS 197 Fig. 7 corners; the table is derived, not typed in.
    assert (aes.SBOX[0x00], aes.SBOX[0x01], aes.SBOX[0x53], aes.SBOX[0xFF]) == (0x63, 0x7C, 0xED, 0x16)
    assert all(aes.INV_SBOX[aes.SBOX[i]] == i for i in range(256))


@pytest.mark.parametrize("n", [0, 15, 17, 24])
def test_invalid_key_length_raises(n):
    with pytest.raises(ValueError):
        aes.expand_key(bytes(n))
    with pytest.raises(ValueError):
        aes.encrypt_block(bytes(n), bytes(16))


@pytest.mark.parametrize("n", [0, 15, 17, 32])
def test_invalid_block_length_raises(n):
    with pytest.raises(ValueError):
        aes.encrypt_block(bytes(16), bytes(n))
    with pytest.raises(ValueError):
        aes.decrypt_block(bytes(16), bytes(n))
