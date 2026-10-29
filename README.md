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

**Status: spec ratified; first RTL core in.** The v1 spec is ratified. RTL exists for
the SHA-256 core only (`rtl/sha256/sha256_core.v`); AES, HMAC, the key ladder, the DRBG
and the key slots are not yet written.

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

## Target specification (ratified for v1)

The full spec is [`spec/target-spec.md`](spec/target-spec.md); each choice has
a record in [`spec/decision-records/`](spec/decision-records/). Summary:

| Parameter | Target | Fallback | Stretch |
|---|---|---|---|
| AES | AES-128, encrypt + decrypt, one round per cycle | encrypt only | AES-256 |
| Hash / MAC | SHA-256 + HMAC-SHA-256 | SHA-256 only | - |
| Key ladder | SP 800-108 counter-mode KDF on HMAC-SHA-256, 4 derived slots | 1 derived slot | AES-CMAC KDF variant |
| DRBG | CTR_DRBG (AES-128, derivation function), seeded and reseeded from `sky130-trng`'s conditioned output | - | prediction-resistance mode |
| Clock (all sky130_fd_sc_hd corners; setup binds at `ss_100C_1v60`) | 50 MHz, target unmeasured | 25 MHz | 100 MHz |
| Key confidentiality | numbered properties in [`spec/key-isolation-properties.md`](spec/key-isolation-properties.md), re-proven on the synthesized netlist where marked | RTL-level property | post-P&R netlist |
| Signoff | DRC + LVS clean | - | - |

The `sky130-trng` interface is in [`spec/trng-interface.md`](spec/trng-interface.md),
pinned in [`reuse.lock.json`](reuse.lock.json).

Maturity ladder: spec ratified → algorithm cores pass the published
known-answer vectors → key-isolation properties proven on the synthesized
netlist → TRNG interface verified against the sibling's RTL → layout
DRC/LVS-clean → timing closed across corners → shuttle seat → measured
silicon. **Current position: spec ratified; the SHA-256 core has a simulation and synthesis
record (a correctness claim and a pre-P&R cell-area figure, nothing more).**

## Repo layout

```
spec/          ratified spec + decision records
rtl/           AES, SHA-256/HMAC, KDF, DRBG, key slots, register interface
verification/  cocotb testbenches, known-answer vectors, formal properties
layout/        GDS + DRC/LVS reports (klayout-tools driven)
measurements/  silicon characterization (empty until tape-out)
```

## Reproduce

CI (`.github/workflows/ci.yml`) needs no PDK and no Docker. Each job calls an
`npm run` script, so a developer runs exactly what CI runs (Python 3.13 and
`pytest` for the model and reuse checks):

```
npm run lint          # compileall on verification/ and flow/, bash -n on scripts
npm run test          # pytest verification/model against the committed vectors
npm run check:reuse   # re-hash reuse.lock.json files; self-test of the checker
npm run check:ci      # all three
```

The PDK-heavy legs stay local (`./scripts/setup-env.sh` provisions `.venv`,
the pinned yosys and the PDK first):

```
./scripts/setup-env.sh                       # provision .venv, pinned yosys, PDK
./verification/rtl/sha256/run.sh             # SHA-256 core: cocotb + Icarus KATs, then klt synthesize
./verification/rtl/sha256/run.sh --record    # same, then write a record under verification/records/
```

The tier-verdict record is re-graded by `.github/workflows/signoff.yml`; to
reproduce it (and the item-10 attestation) at the pinned `klayout-tools`:

```
uvx --from "klayout-tools==0.8.0" klt signoff \
    --manifest manifests/sky130-crypto-rot.json \
    --tiers-doc manifests/design-evidence-tiers.md \
    --format json > manifests/sky130-crypto-rot.signoff.json
```

Exit `3` is expected while any T1 item is unmet. `manifests/README.md` has the
item-10 attestation command. Place-and-route, DRC and LVS (`klt place-and-route`,
`klt drc`, `klt lvs`) have no committed result yet.

CI proves format and known-answer correctness only; it makes no security
claim. See [`verification/README.md`](verification/README.md).

## License

Apache License 2.0 — see [LICENSE](LICENSE).
