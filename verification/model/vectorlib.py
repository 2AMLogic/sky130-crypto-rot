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


def parse_cavp_kbkdf(path):
    """Parse a CAVP KBKDF counter-mode .rsp file.

    Return [(prf, ctrlocation, rlen_bits, fields)] where ``fields`` maps each
    record key (L, KI, FixedInputData, DataBeforeCtrData, ..., KO) to its text.
    """
    records = []
    prf = loc = rlen = None
    cur = None
    for line in path.read_text().splitlines():
        line = line.strip()
        m = re.fullmatch(r"\[(PRF|CTRLOCATION|RLEN)=(\w+)\]", line)
        if m:
            if m.group(1) == "PRF":
                prf = m.group(2)
            elif m.group(1) == "CTRLOCATION":
                loc = m.group(2)
            else:
                rlen = int(m.group(2).split("_")[0])
            continue
        if re.fullmatch(r"COUNT=\d+", line):
            cur = {}
            continue
        m = re.fullmatch(r"(\w+) ?= ?(\w*)", line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2)
            if m.group(1) == "KO":
                records.append((prf, loc, rlen, cur))
                cur = None
    return records


def count_cavp_kbkdf_records(path):
    """Independent count of records per PRF: number of 'KO =' lines under each [PRF=]."""
    counts = {}
    prf = None
    for line in path.read_text().splitlines():
        if line.startswith("[PRF="):
            prf = line[5:].rstrip("]")
        elif line.startswith("KO ="):
            counts[prf] = counts.get(prf, 0) + 1
    return counts


def parse_fips197(path):
    """Parse vectors/fips197.txt into [(section, {FIELD: bytes})], one per [section] block."""
    sections = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.fullmatch(r"\[(\w+)\].*", line)
        if m:
            sections.append((m.group(1), {}))
            continue
        m = re.fullmatch(r"([A-Z]+\d*) = ([0-9a-f]+)", line)
        assert m and sections, f"unparsed line: {line!r}"
        sections[-1][1][m.group(1)] = bytes.fromhex(m.group(2))
    return sections


def count_fips197_records(path):
    """Independent count of vectors: number of 'CIPHERTEXT =' lines."""
    return sum(1 for line in path.read_text().splitlines() if line.startswith("CIPHERTEXT ="))


def parse_cavp_drbg(path):
    """Parse a CAVP CTR_DRBG .rsp into [(section, {field: bytes}, second_additional, returned_bits)].

    Each record is Instantiate(EntropyInput, Nonce, PersonalizationString), Reseed
    (EntropyInputReseed, AdditionalInputReseed), Generate(AdditionalInput) discarded,
    Generate(AdditionalInput) -> ReturnedBits. `section` is e.g. "AES-128 use df".
    """
    records = []
    section = None
    cur = None
    for line in path.read_text().splitlines():
        line = line.strip()
        m = re.fullmatch(r"\[((?:AES-\d+|3KeyTDEA) (?:use|no) df)\]", line)
        if m:
            section = m.group(1)
            continue
        if re.fullmatch(r"COUNT = \d+", line):
            cur = {"section": section, "additional": []}
            continue
        m = re.fullmatch(r"(\w+) =\s*([0-9a-f]*)", line)
        if not m or cur is None:
            continue
        name, value = m.groups()
        if name == "AdditionalInput":
            cur["additional"].append(bytes.fromhex(value))
        else:
            cur[name] = bytes.fromhex(value)
        if name == "ReturnedBits":
            assert len(cur["additional"]) == 2, f"record needs two AdditionalInput lines: {cur}"
            records.append(cur)
            cur = None
    return records


def count_cavp_drbg_records(path):
    """Independent count of vectors: number of 'ReturnedBits =' lines."""
    return sum(1 for line in path.read_text().splitlines() if line.startswith("ReturnedBits ="))
