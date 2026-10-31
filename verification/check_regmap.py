"""Lint the register-map table in spec/decision-records/0009-register-map.md.

Checks, over the rows of the `| Offset | Name | Access | Gate | Ports |` table:
offsets are within the 7-bit word address space; no two registers overlap;
names are unique; an array name `NAME[a..b]` matches its offset range; the
access type is RO, WO, RW or W1C; the gate is a known value; no readable
register (RO, RW, W1C) is wired to a key, seed or key-load port; and the list
of undefined ranges stated in the record equals the one computed from the
table.

    python3 verification/check_regmap.py [0009-register-map.md]

Stdlib only. A table-consistency check; it says nothing about the RTL.
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOC = REPO_ROOT / "spec/decision-records/0009-register-map.md"
ADDR_SPACE = 0x80
ACCESS = {"RO", "WO", "RW", "W1C"}
GATES = {"-", "AES", "HMAC", "HMAC-FEED", "KDF", "KDF-LOAD", "DRBG"}
KEY_PORTS = {"aes_key", "hmac_key", "root_key", "ld_data", "seed"}
ROW = re.compile(r"^\|\s*(0x[0-9A-Fa-f]+)(?:-(0x[0-9A-Fa-f]+))?\s*\|(.*)\|\s*$")
ARRAY = re.compile(r"^([A-Z0-9_]+)\[(\d+)\.\.(\d+)\]$")


def parse_rows(text):
    """Return [(lo, hi, name, access, gate, ports)] from the register table."""
    rows = []
    for line in text.splitlines():
        m = ROW.match(line)
        if not m:
            continue
        lo = int(m.group(1), 16)
        hi = int(m.group(2), 16) if m.group(2) else lo
        cells = [c.strip() for c in m.group(3).split("|")]
        if len(cells) != 4:
            raise ValueError(f"row at {m.group(1)}: expected 5 columns")
        ports = set(re.findall(r"`([^`]+)`", cells[3]))
        rows.append((lo, hi, cells[0], cells[1], cells[2], ports))
    return rows


def unmapped_ranges(rows):
    used = set()
    for lo, hi, *_ in rows:
        used.update(range(lo, hi + 1))
    out, start = [], None
    for a in range(ADDR_SPACE + 1):
        free = a < ADDR_SPACE and a not in used
        if free and start is None:
            start = a
        elif not free and start is not None:
            out.append((start, a - 1))
            start = None
    return out


def fmt_range(lo, hi):
    return f"0x{lo:02X}" if lo == hi else f"0x{lo:02X}-0x{hi:02X}"


def check(doc_path):
    """Return a list of error strings (empty when the table is consistent)."""
    text = Path(doc_path).read_text()
    try:
        rows = parse_rows(text)
    except ValueError as e:
        return [str(e)]
    if not rows:
        return [f"{doc_path}: no register rows found"]
    errors, owner, names = [], {}, set()
    for lo, hi, name, access, gate, ports in rows:
        where = f"{name} ({fmt_range(lo, hi)})"
        if lo > hi or hi >= ADDR_SPACE:
            errors.append(f"{where}: outside the 7-bit word address space")
        if name in names:
            errors.append(f"{where}: duplicate name")
        names.add(name)
        arr = ARRAY.match(name)
        if arr:
            if int(arr.group(2)) != 0 or int(arr.group(3)) - int(arr.group(2)) != hi - lo:
                errors.append(f"{where}: array bounds do not match the offset range")
        elif hi != lo:
            errors.append(f"{where}: a range needs a NAME[0..N] array name")
        if access not in ACCESS:
            errors.append(f"{where}: access {access!r} not in {sorted(ACCESS)}")
        if gate not in GATES:
            errors.append(f"{where}: unknown gate {gate!r}")
        if gate != "-" and access == "RO":
            errors.append(f"{where}: an RO register has no write to gate")
        if access != "WO" and ports & KEY_PORTS:
            errors.append(f"{where}: readable register wired to {sorted(ports & KEY_PORTS)}")
        for a in range(lo, hi + 1):
            if a in owner:
                errors.append(f"{where}: overlaps {owner[a]} at 0x{a:02X}")
            owner[a] = name
    m = re.search(r"not in the table \(([^)]*)\)", text, re.S)
    if not m:
        errors.append(f"{doc_path}: no stated list of undefined ranges")
    else:
        stated = re.findall(r"0x[0-9A-Fa-f]{2}(?:-0x[0-9A-Fa-f]{2})?", m.group(1))
        want = [fmt_range(lo, hi) for lo, hi in unmapped_ranges(rows)]
        if [s.upper().replace("0X", "0x") for s in stated] != want:
            errors.append(f"stated undefined ranges {stated} != computed {want}")
    return errors


def main(argv):
    doc = Path(argv[1]) if len(argv) > 1 else DEFAULT_DOC
    errors = check(doc)
    for e in errors:
        print(f"check_regmap: {e}", file=sys.stderr)
    if not errors:
        print(f"check_regmap: ok ({doc.name})")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
