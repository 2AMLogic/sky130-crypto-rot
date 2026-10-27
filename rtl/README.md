# rtl

- `sha256/sha256_core.v` -- SHA-256 hash core (byte-serial in, 65 cycles per
  block, padding in hardware). Run and verify it with
  `verification/rtl/sha256/run.sh`.
- `aes/aes_core.v` -- AES-128 ECB core, encrypt and decrypt (11 and 21 cycles
  per block), one round per cycle, round keys generated on the fly from a key
  input sampled at `start`; no key-bearing output. Run and verify it with
  `verification/rtl/aes/run.sh`.
