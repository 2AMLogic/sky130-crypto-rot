# 0003 - KDF: SP 800-108 counter mode over HMAC-SHA-256

Status: Accepted. Date: 2026-10-17.

## Decision

Derived key `K(slot) = PRF(K_IN, [1]_32 || Label || 0x00 || Context || [L]_32)`
with PRF = HMAC-SHA-256 (SP 800-108 counter mode, FIPS 198-1).

| Field | Value |
|---|---|
| Counter `[i]_r` | `r = 32` bits, big-endian; one iteration (`n = 1`), so `[1]_32 = 00000001` |
| `Label` | the 8 ASCII bytes `ROT-SLOT` |
| Separator | one `0x00` byte |
| `Context` | 35 bytes: `parent_id` (1 byte: `0xFF` = root key, else a slot index 0-3), `slot_index` (1 byte), `use_mask` (1 byte, see below), `user_context` (32 bytes, software-supplied, all-zero if unused) |
| `[L]_32` | output length in bits, 32-bit big-endian: `00000100` (256) |
| Output length | 256 bits; one HMAC invocation yields the slot key, no truncation |
| `K_IN` | the root key (256 bits, zero-padded to the 64-byte HMAC block) or a parent slot whose use-mask has `KDF-parent` set |
| Message length | 4 + 8 + 1 + 35 + 4 = 52 bytes |

`use_mask` bits: `[0]` AES-encrypt, `[1]` AES-decrypt, `[2]` HMAC key, `[3]`
KDF-parent. The mask is part of the derivation context, so a key derived
with one permission set is a different key from the same slot index derived
with another (key separation by permission).

HMAC cost: ipad/opad key blocks (2 compressions) + inner message
(64 + 52 = 116 bytes -> 2 compressions) + outer (64 + 32 = 96 bytes -> 2
compressions) ~ 6 compressions x 65 cycles = 390 cycles ~ 7.8 us at 50 MHz
(target, unmeasured). The ipad/opad precomputation may be reused when the
same `K_IN` derives several slots; an optimisation, not required by the spec.

Derived-slot count: 4, parent chain depth at most 2 (root -> slot ->
slot); derivation from a locked or zeroized parent is refused.

## Alternatives rejected

- **AES-CMAC counter mode**: uses the AES engine only (no HMAC dependency)
  but the hash engine is in scope anyway; kept as stretch.
- NIST SP 800-56C one-step KDF: no counter-mode flexibility needed.
- Feedback-mode KDF: no benefit for a single 256-bit output.

## Consequences

Golden model (#5) parameters: counter width 32, label `ROT-SLOT`, context
layout above, `L = 256`. KAT: published HMAC-SHA-256 counter-mode vectors
where they exist (the CAVP KDF vectors use fixed-input-data in a different
layout, so the layout above is cross-checked against the golden model, and
the HMAC-SHA-256 primitive is checked against RFC 4231).
