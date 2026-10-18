# verification/model — golden reference models

Pure-Python, standard-library-only models used to score DUT output.

| Module | Primitive | Checked against |
|---|---|---|
| `sha256.py` | SHA-256 (FIPS 180-4) | NIST CAVP SHA-256 ShortMsg and LongMsg (byte-oriented), plus padding-boundary lengths 0/55/56/63/64 |
| `hmac_sha256.py` | HMAC-SHA-256 (RFC 2104) | RFC 4231 test cases 1-7 (case 5 compares the published 128-bit truncation) |
| `kdf.py` | SP 800-108 counter-mode KDF over HMAC-SHA-256 | NIST CAVP KBKDF `KDFCTR_gen.rsp`, HMAC_SHA256 sections (480 records; counter before/after/middle of fixed input, 8/16/24/32-bit counter). Other PRFs in the file are listed as unsupported in the `.source.json` sidecar and not run |
| `aes.py` | AES-128 block encrypt/decrypt and key schedule (FIPS 197); 32-byte keys are accepted but have no committed vector | FIPS 197 Appendix A.1 round keys, Appendix B example, Appendix C.1 (transcribed to `fips197.txt`; the sidecar records the PDF URL and hash) |

Run: `python3 -m pytest verification/model` from the repo root.

## Vectors and provenance

Vector files live verbatim in `../vectors/`. Each has a `<file>.source.json`
sidecar (URL, SHA-256 of the file; for CAVP files also the SHA-256 of the
downloaded archive and the member name). Each vector file has its own test module
whose `test_provenance` recomputes the hash before the vectors run, and
`test_vectors` asserts that vectors run == vectors parsed == records counted
independently in the file. `test_stdlib_only.py` checks the model imports only
the standard library.

`kdf.py` takes counter width, output length and the bytes before and after the
counter as keyword-only parameters with no defaults; the label/context layout
is the caller's, not the model's.

## What this does and does not show

- Shows: the models reproduce the listed published vectors bit-for-bit.
- Does not show: any property of RTL or silicon, constant-time behaviour,
  side-channel resistance, entropy quality, or certification or validation of
  anything. These are stated non-claims. The models are not constant-time and
  must not be used for anything but scoring.

Extension: add a module per primitive and re-export it in `__init__.py`. Any
parameter the spec has not ratified is a keyword argument with no default.
