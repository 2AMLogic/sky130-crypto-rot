from . import hmac_sha256
from .vectorlib import check_provenance, parse_rfc4231

NAME = "rfc4231.txt"


def test_provenance():
    check_provenance(NAME)


def test_vectors():
    path = check_provenance(NAME)
    cases = parse_rfc4231(path)
    assert sorted(cases) == [1, 2, 3, 4, 5, 6, 7]
    run = 0
    for n, (key, data, expected) in cases.items():
        tag = hmac_sha256(key, data)
        # Case 5 publishes only the leftmost 128 bits.
        assert tag[:len(expected)] == expected, f"case {n}"
        assert len(expected) == (16 if n == 5 else 32)
        run += 1
    assert run == len(cases)
