import hashlib
import json

from verification import check_reuse


def _setup(tmp_path, content=b"hello\n"):
    (tmp_path / "vendored.txt").write_bytes(content)
    lock = {
        "schema": 1,
        "imports": [
            {
                "from": "x/y",
                "files": [
                    {
                        "upstream": "u/vendored.txt",
                        "local": "vendored.txt",
                        "sha256": hashlib.sha256(b"hello\n").hexdigest(),
                    },
                    {"upstream": "u/fetched.v", "sha256": "0" * 64},
                ],
            }
        ],
    }
    path = tmp_path / "reuse.lock.json"
    path.write_text(json.dumps(lock))
    return path


def test_clean_pass_and_fetched_skipped(tmp_path):
    errors, skipped = check_reuse.check(_setup(tmp_path))
    assert errors == []
    assert len(skipped) == 1 and "fetched.v" in skipped[0]


def test_hash_mismatch_fails(tmp_path):
    errors, _ = check_reuse.check(_setup(tmp_path, content=b"hellp\n"))
    assert len(errors) == 1 and "sha256" in errors[0]


def test_missing_local_file_fails(tmp_path):
    lock = _setup(tmp_path)
    (tmp_path / "vendored.txt").unlink()
    errors, _ = check_reuse.check(lock)
    assert len(errors) == 1 and "missing file" in errors[0]


def test_repo_lock_is_clean():
    errors, _ = check_reuse.check(check_reuse.REPO_ROOT / "reuse.lock.json")
    assert errors == []
