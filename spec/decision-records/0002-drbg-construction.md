# 0002 - DRBG construction: CTR_DRBG, AES-128, with derivation function

Status: Accepted (ratifies the v1 spec). Date: 2026-10-17.

## Context

The block needs a DRBG seeded from `sky130-trng`'s conditioned output
(non-vetted CRC-32 conditioner, 256 raw bits per 32-bit word, entropy
provisional until silicon). The golden model (#5) treats derivation function,
key size and reseed interval as parameters; this record fixes their values.

## Decision

SP 800-90A **CTR_DRBG**, AES-128 (keylen 128, outlen 128, seedlen 256),
**with the block-cipher derivation function** (df), `ctr_len = 128`.

| Parameter | Value |
|---|---|
| Security strength requested | 128 bits (a design level, not a validation claim) |
| df | yes (`Block_Cipher_df`, AES-128 CBC-MAC, outlen 128) |
| Instantiate input | `entropy_input` = TRNG words 0-7 (256 bits), `nonce` = words 8-15 (256 bits), `personalization_string` = empty. 16 words total |
| Reseed input | `entropy_input` = 8 TRNG words (256 bits), `additional_input` = empty |
| Word to byte order | words are concatenated in arrival order, each word most-significant byte first |
| Max bits per `generate` request | 1024 (8 blocks) |
| `reseed_interval` | 2^16 generate requests |
| Prediction resistance | not in v1 (stretch) |
| Additional input on `generate` | not supported in v1 |
| After `generate` | the standard `Update` (state refresh) is performed every request |
| Output before instantiate | never (property P-7) |
| TRNG `gated` / `alarm` | per `trng-interface.md` section 3.4 |

Only the AES forward cipher is used, so the encrypt-only AES fallback does
not affect the DRBG. The DRBG shares the AES engine; it holds the engine
exclusively while a request runs and the bus cannot use the engine's key
input during that time.

## Why df, and why the open question stays open

The conditioner is non-vetted and its output is not claimed to be full
entropy. Without df, SP 800-90A requires `entropy_input` of exactly seedlen
bits with full entropy, a claim this block cannot make. With df, input of
arbitrary length is compressed, so what is assumed is "enough min-entropy
distributed across 512 conditioned bits", not "each bit is full entropy".
At the sibling's design target (H = 0.5 per raw bit, provisional) 512
conditioned bits correspond to 4096 raw bits. That arithmetic is a
design margin, **not an entropy claim**.

**Open question from the issue**: is CTR_DRBG on a non-vetted conditioned
source right, or should seeding run the raw stream through a vetted
conditioner here (SP 800-90B approved, e.g. HMAC-SHA-256 or AES-CBC-MAC
based)? Decision for v1: **take the sibling's conditioned stream** and
apply df; this block does not duplicate a conditioner (scope discipline: the
conditioner is the sibling's). Raw mode into the in-block SHA-256 or AES
engine as a vetted conditioner is the recorded alternative: it costs no new
primitive (both engines exist) but needs raw-stream throughput of
`seed_bits x ratio` (at 50 kbps raw, 1024 raw bits = 20 ms per 256-bit
output at ratio 4) and makes this block responsible for entropy accounting
that belongs with the source. If the sibling's conditioned output is
later judged unsuitable, revisit; that decision would be a new record and a
change to `trng-interface.md` section 3.3.

## Alternatives rejected

- No df, 256-bit seed: needs a full-entropy claim we cannot make.
- AES-256 CTR_DRBG: stretch; bigger key schedule, longer seeds (seedlen 384);
  adds nothing at the 128-bit design level. Revisit if AES-256 is built.
- HMAC_DRBG / Hash_DRBG: would reuse SHA but ties DRBG throughput to the
  slower hash engine and adds a second DRBG family; CTR_DRBG is in scope per
  the README.

## Consequences

The golden model parameters are: AES-128, df=yes, ctr_len=128,
seed_len=256, instantiate input 512 bits, reseed input 256 bits,
reseed_interval 2^16, max_request 1024 bits, empty personalization.
Known-answer testing covers the algorithm only; entropy remains
provisional.
