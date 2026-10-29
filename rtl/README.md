# rtl

- `sha256/sha256_core.v` -- SHA-256 hash core (byte-serial in, 65 cycles per
  block, padding in hardware). Run and verify it with
  `verification/rtl/sha256/run.sh`.
- `hmac/hmac_sha256.v` -- HMAC-SHA-256 sequencer around one `sha256_core`
  (slot key up to 32 bytes, plus a byte-stream key port for longer keys).
  Run and verify it with `verification/rtl/hmac/run.sh`.
- `aes/aes_core.v` -- AES-128 ECB core, encrypt and decrypt (11 and 21 cycles
  per block), one round per cycle, round keys generated on the fly from a key
  input sampled at `start`; no key-bearing output. Run and verify it with
  `verification/rtl/aes/run.sh`.
- `drbg/ctr_drbg.v` -- SP 800-90A CTR_DRBG (AES-128, block-cipher df, no
  prediction resistance), engine-less: it drives an AES master port and reads
  its seed from an input. Seed widths and the reseed interval are elaboration
  parameters (shipped 16/8 words, 2^16). `drbg/drbg_top.v` ties it to an
  `aes_core` and `trng_if` for the benches. Run and verify it with
  `verification/rtl/drbg/run.sh`.
- `trng_if/trng_if.v` -- this block's side of the `sky130-trng` interface:
  clock-domain crossing, `t_fall` sampling and gating, seed buffer, write-only
  bus sequencer, alarm zeroize. CDC notes: `trng_if/README.md`. Run and verify
  it with `verification/rtl/trng_if/run.sh`; P-7, P-8 and P-9 with
  `verification/formal/run.sh`.
- `keyladder/keyladder.v` -- key ladder: 4 derived 256-bit slots with per-slot
  use-mask, lock and chain depth, SP 800-108 derivation over `hmac_sha256`
  (decision record 0003), write-only software load, engine key release gated
  on the use-mask, `zeroize` input; slot contents reach only the engine key
  outputs. Run and verify it with `verification/rtl/keyladder/run.sh`.
