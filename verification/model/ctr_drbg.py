"""NIST SP 800-90A CTR_DRBG (AES), a bit-exact scoring reference.

Prediction resistance is not modelled. Only the AES forward cipher is used.
``use_df``, ``key_bits`` and ``reseed_interval`` have no defaults. Not
constant-time; a passing vector is a correctness claim and says nothing about
the quality of any seed.
"""

from .aes import encrypt_block

OUTLEN = 16  # AES block, bytes
_MAX_REQUEST_BYTES = 1 << 16  # SP 800-90A max_number_of_bits_per_request, 2^19 bits
_MASK128 = (1 << 128) - 1


def _xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def _bcc(key, data):
    chaining = bytes(OUTLEN)
    for i in range(0, len(data), OUTLEN):
        chaining = encrypt_block(key, _xor(chaining, data[i:i + OUTLEN]))
    return chaining


def block_cipher_df(data, nbytes, *, key_bits):
    """Block_Cipher_df (SP 800-90A section 10.3.2): return nbytes derived from data."""
    keylen = key_bits // 8
    s = len(data).to_bytes(4, "big") + nbytes.to_bytes(4, "big") + data + b"\x80"
    s += bytes(-len(s) % OUTLEN)
    temp = b""
    i = 0
    while len(temp) < keylen + OUTLEN:
        temp += _bcc(bytes(range(keylen)), i.to_bytes(4, "big") + bytes(OUTLEN - 4) + s)
        i += 1
    key, x = temp[:keylen], temp[keylen:keylen + OUTLEN]
    out = b""
    while len(out) < nbytes:
        x = encrypt_block(key, x)
        out += x
    return out[:nbytes]


class CtrDrbg:
    def __init__(self, *, use_df, key_bits, reseed_interval):
        if key_bits not in (128, 256):
            raise ValueError("key_bits must be 128 or 256")
        if reseed_interval < 1:
            raise ValueError("reseed_interval must be positive")
        self.use_df = bool(use_df)
        self.key_bits = key_bits
        self.reseed_interval = reseed_interval
        self.keylen = key_bits // 8
        self.seedlen = self.keylen + OUTLEN
        self._instantiated = False
        self.key = self.v = self.reseed_counter = None

    def _seed_material(self, entropy_input, nonce, extra):
        """Seed material for instantiate (extra = personalization) or reseed (extra = additional)."""
        if self.use_df:
            return block_cipher_df(entropy_input + nonce + extra, self.seedlen, key_bits=self.key_bits)
        if len(entropy_input) != self.seedlen or nonce:
            raise ValueError("no derivation function: entropy_input must be seedlen bytes, no nonce")
        if len(extra) > self.seedlen:
            raise ValueError("input longer than seedlen with no derivation function")
        return _xor(entropy_input, extra + bytes(self.seedlen - len(extra)))

    def _seed_material_additional(self, additional):
        if self.use_df:
            return block_cipher_df(additional, self.seedlen, key_bits=self.key_bits)
        if len(additional) > self.seedlen:
            raise ValueError("additional input longer than seedlen with no derivation function")
        return additional + bytes(self.seedlen - len(additional))

    def _update(self, provided):
        assert len(provided) == self.seedlen
        v = int.from_bytes(self.v, "big")
        temp = b""
        while len(temp) < self.seedlen:
            v = (v + 1) & _MASK128
            temp += encrypt_block(self.key, v.to_bytes(OUTLEN, "big"))
        temp = _xor(temp[:self.seedlen], provided)
        self.key, self.v = temp[:self.keylen], temp[self.keylen:]

    def instantiate(self, entropy_input, nonce=b"", personalization=b""):
        seed = self._seed_material(entropy_input, nonce, personalization)
        self.key, self.v = bytes(self.keylen), bytes(OUTLEN)
        self._update(seed)
        self.reseed_counter = 1
        self._instantiated = True

    def reseed(self, entropy_input, additional=b""):
        if not self._instantiated:
            raise RuntimeError("reseed before instantiate")
        self._update(self._seed_material(entropy_input, b"", additional))
        self.reseed_counter = 1

    def generate(self, nbytes, additional=b""):
        if not self._instantiated:
            raise RuntimeError("generate before instantiate")
        if self.reseed_counter > self.reseed_interval:
            raise RuntimeError("reseed required: reseed_interval reached")
        if not 0 < nbytes <= _MAX_REQUEST_BYTES:
            raise ValueError("request size out of range")
        if additional:
            add = self._seed_material_additional(additional)
            self._update(add)
        else:
            add = bytes(self.seedlen)
        v = int.from_bytes(self.v, "big")
        out = b""
        while len(out) < nbytes:
            v = (v + 1) & _MASK128
            out += encrypt_block(self.key, v.to_bytes(OUTLEN, "big"))
        self.v = v.to_bytes(OUTLEN, "big")
        self._update(add)
        self.reseed_counter += 1
        return out[:nbytes]
