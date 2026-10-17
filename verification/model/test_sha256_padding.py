"""Padding-boundary lengths, scored against a fixed digest table (no hashlib in the model)."""

from . import sha256

# Digests of b"a" * n, computed once with an independent implementation (hashlib).
EXPECTED = {
    0: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    55: "9f4390f8d30c2dd92ec9f095b65e2b9ae9b0a925a5258e241c9f1e910f734318",
    56: "b35439a4ac6f0948b6d6f9e3c6af0f5f590ce20f1bde7090ef7970686ec6738a",
    63: "7d3e74a05d7db15bce4ad9ec0658ea98e3f06eeecf16b4c6fff2da457ddc2f34",
    64: "ffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb",
}


def test_padding_boundaries():
    for n, digest in EXPECTED.items():
        assert sha256(b"a" * n).hex() == digest, n
