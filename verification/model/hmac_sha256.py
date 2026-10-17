"""HMAC-SHA-256 per RFC 2104 / FIPS 198-1 over the in-repo SHA-256 model."""

from .sha256 import BLOCK_SIZE, sha256


def hmac_sha256(key, msg):
    """Return the full 32-byte HMAC-SHA-256 tag of ``msg`` under ``key``."""
    key = bytes(key)
    if len(key) > BLOCK_SIZE:
        key = sha256(key)
    key = key.ljust(BLOCK_SIZE, b"\x00")
    ipad = bytes(b ^ 0x36 for b in key)
    opad = bytes(b ^ 0x5C for b in key)
    return sha256(opad + sha256(ipad + bytes(msg)))
