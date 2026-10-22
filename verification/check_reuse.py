"""Re-hash every file in reuse.lock.json against its stamped sha256.

For each import file the local copy (`local`, else the `upstream` path) is
hashed and compared to `sha256`. A mismatch or a missing file fails. Entries
with no `local` whose `upstream` path is not in this repo (fetched imports
that are not copied in) are skipped and reported.

    python3 verification/check_reuse.py [path/to/reuse.lock.json]

Stdlib only. Checks that the vendored bytes match the pin; it makes no claim
about the upstream commit itself.
"""
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def check(lock_path, root=None):
    """Return (errors, skipped) for the lock at lock_path, files under root."""
    lock_path = Path(lock_path)
    root = Path(root) if root else lock_path.parent
    lock = json.loads(lock_path.read_text())
    errors, skipped = [], []
    for imp in lock["imports"]:
        for entry in imp["files"]:
            local = entry.get("local")
            path = root / (local or entry["upstream"])
            label = f"{imp['from']}: {local or entry['upstream']}"
            if not local and not path.is_file():
                skipped.append(label)
                continue
            if not path.is_file():
                errors.append(f"{label}: missing file")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != entry["sha256"]:
                errors.append(f"{label}: sha256 {digest} != stamped {entry['sha256']}")
    return errors, skipped


def main(argv):
    lock = Path(argv[1]) if len(argv) > 1 else REPO_ROOT / "reuse.lock.json"
    errors, skipped = check(lock)
    for s in skipped:
        print(f"skip (no local copy): {s}")
    for e in errors:
        print(f"FAIL {e}")
    if errors:
        return 1
    print(f"reuse OK: {lock.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
