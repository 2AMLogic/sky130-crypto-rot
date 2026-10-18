"""SP 800-108 counter-mode KDF over HMAC-SHA-256 (the in-repo model)."""

from .hmac_sha256 import hmac_sha256

_PRF_BITS = 256


def kdf_ctr_hmac_sha256(ki, *, counter_bits, out_bits, before, after):
    """Return the leftmost ``out_bits`` bits of the counter-mode KDF output.

    For i = 1..ceil(out_bits / 256):
        K(i) = HMAC-SHA-256(ki, before || [i]_counter_bits || after)
    with [i]_r big-endian. The caller supplies everything around the counter
    (label, separator, context, [L]); no layout, counter width or output
    length is defaulted. ``out_bits`` must be a multiple of 8.
    """
    if counter_bits <= 0 or counter_bits % 8:
        raise ValueError("counter_bits must be a positive multiple of 8")
    if out_bits <= 0 or out_bits % 8:
        raise ValueError("out_bits must be a positive multiple of 8")
    n = -(-out_bits // _PRF_BITS)
    if n >= 1 << counter_bits:
        raise ValueError("output needs more iterations than the counter can hold")
    before, after = bytes(before), bytes(after)
    out = b"".join(
        hmac_sha256(ki, before + i.to_bytes(counter_bits // 8, "big") + after)
        for i in range(1, n + 1)
    )
    return out[: out_bits // 8]
