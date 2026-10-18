"""AES block cipher per FIPS 197: key expansion, encrypt and decrypt of one block.

Textbook, table-free and not constant-time. The S-box is derived at import from
the GF(2^8) inverse and the affine map. The key size is a parameter with no
default: 16 selects AES-128 (10 rounds); 32 (AES-256) is accepted as a stretch
and is checked only if its published vector is committed.
"""

BLOCK_SIZE = 16
_ROUNDS = {16: 10, 32: 14}


def _xtime(a):
    a <<= 1
    return (a ^ 0x11B) & 0xFF if a & 0x100 else a


def _mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xtime(a)
        b >>= 1
    return r


def _make_sbox():
    sbox = []
    for x in range(256):
        inv = 0 if x == 0 else next(y for y in range(1, 256) if _mul(x, y) == 1)
        s = inv
        for i in range(1, 5):
            s ^= ((inv << i) | (inv >> (8 - i))) & 0xFF
        sbox.append(s ^ 0x63)
    return sbox


SBOX = _make_sbox()
INV_SBOX = [0] * 256
for _i, _s in enumerate(SBOX):
    INV_SBOX[_s] = _i


def _check(data, sizes, what):
    data = bytes(data)
    if len(data) not in sizes:
        raise ValueError(f"{what} must be {' or '.join(map(str, sizes))} bytes, got {len(data)}")
    return data


def expand_key(key):
    """Return the 4-byte words w[0 .. 4*(Nr+1)-1] for a 16- or 32-byte key."""
    key = _check(key, _ROUNDS, "key")
    nk = len(key) // 4
    total = 4 * (_ROUNDS[len(key)] + 1)
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, total):
        t = list(w[i - 1])
        if i % nk == 0:
            t = [SBOX[b] for b in t[1:] + t[:1]]
            t[0] ^= rcon
            rcon = _xtime(rcon)
        elif nk > 6 and i % nk == 4:
            t = [SBOX[b] for b in t]
        w.append([a ^ b for a, b in zip(w[i - nk], t)])
    return [bytes(x) for x in w]


def round_keys(key):
    """Return the 16-byte round keys (Nr + 1 of them) for ``key``."""
    w = expand_key(key)
    return [b"".join(w[4 * r:4 * r + 4]) for r in range(len(w) // 4)]


def _add_key(state, rk):
    return [s ^ k for s, k in zip(state, rk)]


# State is a flat 16-byte list in input order: index = 4*column + row.
def _shift_rows(s):
    return [s[4 * ((c + r) % 4) + r] for c in range(4) for r in range(4)]


def _inv_shift_rows(s):
    return [s[4 * ((c - r) % 4) + r] for c in range(4) for r in range(4)]


def _mix(s, coeffs):
    out = []
    for c in range(4):
        col = s[4 * c:4 * c + 4]
        for r in range(4):
            v = 0
            for j in range(4):
                v ^= _mul(coeffs[(j - r) % 4], col[j])
            out.append(v)
    return out


def encrypt_block(key, block):
    """Encrypt one 16-byte block."""
    block = _check(block, (BLOCK_SIZE,), "block")
    rks = round_keys(key)
    s = _add_key(list(block), rks[0])
    for rnd in range(1, len(rks)):
        s = _shift_rows([SBOX[b] for b in s])
        if rnd != len(rks) - 1:
            s = _mix(s, (2, 3, 1, 1))
        s = _add_key(s, rks[rnd])
    return bytes(s)


def decrypt_block(key, block):
    """Decrypt one 16-byte block."""
    block = _check(block, (BLOCK_SIZE,), "block")
    rks = round_keys(key)
    s = _add_key(list(block), rks[-1])
    for rnd in range(len(rks) - 2, -1, -1):
        s = [INV_SBOX[b] for b in _inv_shift_rows(s)]
        s = _add_key(s, rks[rnd])
        if rnd != 0:
            s = _mix(s, (14, 11, 13, 9))
    return bytes(s)
