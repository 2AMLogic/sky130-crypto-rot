# sky130-crypto-rot

A small cryptographic root of trust on the
[SkyWater sky130](https://github.com/google/skywater-pdk) open PDK — AES,
SHA-256 with HMAC, a key ladder, and a deterministic random bit generator
seeded by the sibling canary
[sky130-trng](https://github.com/2AMLogic/sky130-trng) — taken from RTL
toward DRC/LVS-clean GDS by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the
open-source digital flow: cocotb + Icarus for verification, Yosys for
synthesis, OpenROAD for place-and-route.

**Status: just opened, specification phase.** Nothing is designed yet.

**Built agent-native.** Every specification, decision record, testbench, and
line of documentation here is produced by AI agents working from a ratified
spec and an append-only evidence trail — not human-authored work that agents
merely assisted with. Verification is the product: every claim traces to a
recorded result. Where the agents hit friction with the open-source tooling —
most often [klayout-tools](https://github.com/2AMLogic/klayout-tools) — that
friction is filed as a public issue against the tool itself, so the fix
benefits everyone using sky130, not just this repo.

## Why this block, on this node

The fleet already has an entropy source on sky130 (`sky130-trng`) and a
public-key arithmetic core (`sky130-modexp`). What it does not have is the
block that turns entropy into keys and uses them: symmetric encryption, a
hash, keyed derivation, and a DRBG behind a single register interface whose
key material never reaches the bus.

That makes this a digital block whose most important
properties are **not functional**. "AES gives the right ciphertext" is a
known-answer test. "No sequence of bus accesses can read a derived key" is
not — it is a property of every path in the netlist, and it has to hold after
synthesis and place-and-route, not only in RTL. Proving properties like that
with an open flow is the reason the block exists.

## Scope

- **In scope**: AES-128 encrypt/decrypt (FIPS 197); SHA-256 (FIPS 180-4) and
  HMAC-SHA-256 (FIPS 198-1); a key ladder deriving working keys from a root
  key via a counter-mode KDF (SP 800-108); a CTR_DRBG (SP 800-90A) seeded
  from `sky130-trng`'s conditioned output; key slots that are write-only or
  never bus-visible; a lifecycle/fault state that zeroizes on a TRNG alarm.
- **From a sibling**: the entropy source is `sky130-trng`'s, taken by pinned
  reference. This repo specifies its side of that interface and does not
  redesign the TRNG, its health tests or its conditioner.
- **Not in scope**: public-key arithmetic (`sky130-modexp` builds it; adopt
  it or record why not if it is ever added), non-volatile root-key storage
  (the root key arrives on a port), and side-channel countermeasures in v1.
- **Not claimed**: any certification, validation or side-channel
  resistance. Known-answer tests show the algorithms are implemented
  correctly; they say nothing about leakage.

## Target specification (DRAFT — engineering to ratify, see issue #1)

| Parameter | Target | Fallback | Stretch |
|---|---|---|---|
| AES | AES-128, encrypt + decrypt, iterative round datapath | encrypt only | AES-256 |
| Hash / MAC | SHA-256 + HMAC-SHA-256 | SHA-256 only | — |
| Key ladder | SP 800-108 counter-mode KDF on HMAC-SHA-256, ≥ 4 derived slots | 1 derived slot | AES-CMAC KDF variant |
| DRBG | CTR_DRBG (AES-128), seeded and reseeded from `sky130-trng` | — | prediction-resistance mode |
| Clock (all sky130_fd_sc_hd corners) | 50 MHz | 25 MHz | 100 MHz |
| Key confidentiality | formal property: no bus read returns key material, post-synthesis netlist | RTL-level property | post-P&R netlist |
| Signoff | DRC + LVS clean | — | — |

Maturity ladder: spec ratified → algorithm cores pass the published
known-answer vectors → key-isolation properties proven on the synthesized
netlist → TRNG interface verified against the sibling's RTL → layout
DRC/LVS-clean → timing closed across corners → shuttle seat → measured
silicon. **Current position: pre-spec.**

## Repo layout

```
spec/          ratified spec + decision records
rtl/           AES, SHA-256/HMAC, KDF, DRBG, key slots, register interface
verification/  cocotb testbenches, known-answer vectors, formal properties
layout/        GDS + DRC/LVS reports (klayout-tools driven)
measurements/  silicon characterization (empty until tape-out)
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
