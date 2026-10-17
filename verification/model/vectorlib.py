"""Helpers shared by the vector tests: provenance check and file parsers."""

import hashlib
import json
import re
from pathlib import Path

VECTOR_DIR = Path(__file__).resolve().parent.parent / "vectors"


def check_provenance(name):
    """Recompute the SHA-256 of vectors/<name> against its sidecar; return the path."""
    path = VECTOR_DIR / name
    sidecar = json.loads((VECTOR_DIR / (name + ".source.json")).read_text())
    for field in ("url", "sha256"):
        assert sidecar.get(field), f"{name}.source.json lacks {field}"
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == sidecar["sha256"], f"{name}: sha256 {actual} != recorded {sidecar['sha256']}"
    return path


def parse_cavp_sha(path):
    """Parse a CAVP SHA byte-oriented .rsp file into [(msg_bytes, md_bytes)]."""
    vectors = []
    cur = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        m = re.fullmatch(r"(Len|Msg|MD) = (\w+)", line)
        if not m:
            continue
        cur[m.group(1)] = m.group(2)
        if m.group(1) == "MD":
            assert set(cur) == {"Len", "Msg", "MD"}, f"incomplete vector before: {line}"
            nbytes = int(cur["Len"]) // 8
            vectors.append((bytes.fromhex(cur["Msg"])[:nbytes], bytes.fromhex(cur["MD"])))
            cur = {}
    return vectors


def count_cavp_records(path):
    """Independent count of vectors: number of 'Len =' lines."""
    return sum(1 for line in path.read_text().splitlines() if line.startswith("Len ="))


def parse_rfc4231(path):
    """Return {case: (key, data, hmac_sha256_prefix)} for RFC 4231 sections 4.2-4.8."""
    lines = path.read_text().splitlines()
    cases = {}
    case = None
    for i, line in enumerate(lines):
        m = re.match(r"4\.\d+\.\s+Test Case (\d+)$", line)
        if m:
            case = int(m.group(1))
            cases[case] = {}
            continue
        if case is None or line.startswith("RFC 4231") or line.startswith("Nystrom"):
            continue
        m = re.match(r"   (Key|Data|HMAC-SHA-256)\s*=?\s+(\S.*)$", line)
        if m:
            chunks = []
            j = i
            while True:
                body = lines[j][15:] if j > i else m.group(2)
                body = re.sub(r"\(.*", "", body).strip()
                chunks.append(body)
                nxt = lines[j + 1] if j + 1 < len(lines) else ""
                if not re.match(r"^ {18}[0-9a-f]", nxt):
                    break
                j += 1
            cases[case][m.group(1)] = bytes.fromhex("".join(chunks))
    return {
        c: (v["Key"], v["Data"], v["HMAC-SHA-256"])
        for c, v in cases.items()
        if {"Key", "Data", "HMAC-SHA-256"} <= set(v)
    }
