from . import sha256
from .vectorlib import check_provenance, count_cavp_records, parse_cavp_sha

NAME = "SHA256LongMsg.rsp"


def test_provenance():
    check_provenance(NAME)


def test_vectors():
    path = check_provenance(NAME)
    vectors = parse_cavp_sha(path)
    assert len(vectors) == count_cavp_records(path) > 0
    run = 0
    for msg, md in vectors:
        assert sha256(msg) == md, f"len={len(msg)}"
        run += 1
    assert run == len(vectors)
