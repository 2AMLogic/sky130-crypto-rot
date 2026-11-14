# Roadmap

`sky130-crypto-rot` takes a small cryptographic root of trust (AES-128, SHA-256/HMAC, a key ladder
and a CTR_DRBG seeded from `sky130-trng`) from a ratified spec toward DRC/LVS-clean sky130 GDS with
an open flow, and its hard part is proving key isolation on the netlist rather than only in RTL.

Status as of 2026-11-13, `main` @ `522931b`.

`WORK_PLAN.md` is the machine-generated view of label state and `WORK_LOG.md` the merge history;
this file is the plan and its reasons. The verdict of record is
[`manifests/sky130-crypto-rot.signoff.json`](../manifests/sky130-crypto-rot.signoff.json), and the
tracker is [#3](https://github.com/2AMLogic/sky130-crypto-rot/issues/3).

## Where it stands

On the README's maturity ladder the block is at the **algorithm-core rung**, with the key-isolation
rung partly recorded and nothing beyond it claimed.

- **Spec ratified for v1**: `spec/target-spec.md`, `spec/trng-interface.md`,
  `spec/key-isolation-properties.md`, decision records 0001-0008. It defines no register map yet
  (#89).
- **Six RTL blocks, each with a bench, negative controls and a record** (`rtl/README.md`,
  `verification/records/`): `sha256_core`, `hmac_sha256`, `aes_core`, `keyladder`, `ctr_drbg` (+
  `drbg_top`), `trng_if`. Each sim+synth record is RTL simulation plus one `klt synthesize` run at
  `tt_025C_1v80`; no STA and no gate-level simulation has been run on any of them.
- **Key-isolation properties recorded so far** (bounds are in the records):
  - P-5, P-6: proven on RTL and on the synthesized `keyladder` netlist; P-2 cone check passes on
    both; P-1 at the key-ladder module boundary is bounded only (RTL depth 24, netlist depth 10,
    against a 478-cycle derivation) (`verification/records/keyladder-formal/`).
  - P-7, P-8, P-9: proven on RTL only, AES abstracted (`verification/records/drbg-trng-formal/`).
    The spec marks all three N (netlist-provable); the netlist half is not done.
  - P-1 at the bus, P-3, P-4, P-10, P-11, P-12, P-14 as recorded results, and P-13: not started.
    Most need the top level.
- **TRNG interface**: `drbg_top` passes against a port-protocol stub and against the sibling's RTL
  at the pinned commit, with the sibling's start-up length and conditioner block shortened by
  parameter (`verification/records/trng-if-sim/`).
- **T1 checklist** (`klt signoff`, klayout-tools 0.8.0): **2 of 11 met, 1 not applicable.**

| Item | Status | Issue |
|---|---|---|
| 1 Design sources | unmet: no top level, no committed netlist | #46 (#87, #88) |
| 2 Layout | unmet | #47 |
| 3 DRC clean | unmet | #48 |
| 4 LVS clean | unmet | #49 |
| 5 Corner verification | unmet | #50 |
| 6 Monte Carlo | not applicable (`manifests/item6-na-statement.json`) | - |
| 7 Post-layout verification | unmet | #82 |
| 8 Characterization report | unmet | #83 |
| 9 Testbenches shipped | met (`scripts/cold-start-benches.sh`, attested) | - |
| 10 Repo hygiene | met (attested; CI re-hashes both envelopes) | - |
| 11 Power delivery | unmet | #53 |

Since the cores landed (the last on 2026-10-29), most merged work has been on the evidence
machinery: one record library, one bench driver, negative controls that must prove the fault was
caught, and attestation envelopes that fail CI when they go stale.

## Now

1. **Land the register map** (#89, PR #90). Done when `spec/decision-records/0009-register-map.md`
   and its lint (`verification/check_regmap.py`, wired into `npm run check:ci`) are on `main`. The
   PR has one content conflict (`package.json`) against a `main` that has moved well past its base,
   and needs a fresh head so every check runs. This is the head of the whole T1 chain.
2. **Remove the 12 hand-copied negative-control request files** (#161). Done when each
   `--negative-control` run derives its request from the positive one and the item-9 envelope is
   re-attested.
3. **Finish the two record-accuracy changes in review**: PR #171 (#164, approved) and PR #170 (#165,
   changes requested, CI failing). Done when both are merged; #169 (a live key-ladder formal run
   confirming the depth reader) follows #165.
4. **Bring the remaining hand-copied klayout-tools pins under `check_pins.py`** (#172). Done when
   `npm run lint` fails on a mismatch in `signoff.yml` or `manifests/README.md`.
5. **Re-prove P-7, P-8 and P-9 on the synthesized netlist** (no issue; seed 1). Done when a
   `drbg-trng-formal` record carries a netlist row and a netlist negative control for each property,
   or records the depth reached.
6. **First timing measurement** (no issue; seed 2). Every timing row in the spec is "target,
   unmeasured". Done when a record states setup slack for `aes_core` and `sha256_core` at
   `ss_100C_1v60` against a 20 ns clock, labelled pre-layout, or the tool gap that prevented it is
   filed upstream.
7. **Gate-level simulation of the core known-answer tests** (no issue; seed 3). Done when the AES
   and SHA-256 vectors pass on the `klt synthesize` netlists and the result is in a record, with a
   negative control.
8. **Run `drbg_top` against the sibling's RTL at unshortened parameters** (no issue; seed 4). Done
   when the `trng-if-sim` record no longer lists the full start-up and 256-bit conditioner block
   under "Not covered".

Items 5 to 8 need nothing from the top level: they deepen evidence on blocks that are already
merged, and each is the first use here of a flow step (netlist formal on the DRBG path, STA,
gate-level simulation) that the top level will need anyway.

## Next

- **Top-level RTL and bus-level bench** (#87) after #89. Done when `rtl/crypto_rot_top.v` passes
  end-to-end KATs through the bus, one test per zeroize event, a protocol checker and negative
  controls, with a record.
- **Top-level netlist, freshness check, P-12 on the netlist, `--attest 1`** (#88) after #87. Done
  when `klt signoff` grades item 1 `met`; closes #46.
- **Bus-level P-1, P-3, P-4, P-10, P-11, P-14** after #87. No issue yet; file them once the
  top-level port and register names exist, since each property is stated over them.
- **Routed GDS** (#47) after #88; then **DRC** (#48), **LVS** (#49), **power delivery** (#53) and
  **corner verification** (#50) on that layout.
- **Post-layout verification** (#82) and the **characterization report** (#83) after #47 and #50.
- **Include the shared bench driver in the item-9 inventory** (#163), currently blocked.

## Later

- **P-13, sequential equivalence of netlist to RTL.** Does `klt equiv` scale to the full design with
  its key schedule? If not, the properties are re-run on each netlist rather than carried (spec,
  P-13).
- **Unbounded P-1.** Can the two-trace product close by induction without hand-written
  strengthening, or at a depth that covers one 478-cycle derivation on the mapped netlist? If not,
  P-1 stays at the depth reached (spec, Open questions 1 and 3).
- **Area budget.** The 0.50 mm^2 figure is a placeholder "to be re-set from the first SYNTH report";
  re-setting it is a spec change with a decision record, once the top level synthesizes.
- **`gated`-persists-then-`RESEED_REQUIRED`.** The spec names the transition but no persistence
  threshold, so none is implemented; the threshold needs a decision record before it can be built or
  tested.
- **Timing closed across corners, then a shuttle seat and measured silicon**: the last ladder rungs,
  all after T1 evidence exists.

## Blocked and waiting

- Everything from #87 down the T1 chain waits on the register map (#89).
- Three scope-reduction proposals wait on a maintainer decision: #121 (drop the vendored tiers doc),
  #129 (unify the two formal harnesses), #134 (drop the three vendored `sky130-modexp` workaround
  files). #129 and #134 touch the formal and gate-level paths that Now items 5 and 7 use; whichever
  lands second rebases.

## Not planned

Per the ratified spec and the README: public-key arithmetic (the sibling `sky130-modexp`'s), a TRNG,
health tests or conditioner (the sibling `sky130-trng`'s), non-volatile root-key storage, scan or
debug access, side-channel countermeasures in v1 (decision record 0008), and any certification,
validation or full-entropy claim. AES-256, AXI4-Lite and the 100 MHz clock are stretch rows that do
not drive architecture before the target closes.
