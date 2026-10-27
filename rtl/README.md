# rtl

- `sha256/sha256_core.v` -- SHA-256 hash core (byte-serial in, 65 cycles per
  block, padding in hardware). Run and verify it with
  `verification/rtl/sha256/run.sh`.
- `hmac/hmac_sha256.v` -- HMAC-SHA-256 sequencer around one `sha256_core`
  (slot key up to 32 bytes, plus a byte-stream key port for longer keys).
  Run and verify it with `verification/rtl/hmac/run.sh`.
