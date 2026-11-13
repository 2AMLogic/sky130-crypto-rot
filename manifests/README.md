# Block manifest and tier-verdict record

This directory holds this block's `klt signoff` input and its committed
output, so the gap to the klayout-tools T1 checklist is read from a tool
rather than from prose.

## Files

- **`sky130-crypto-rot.json`** — the block manifest: `block`,
  `kind: digital`, and an `evidence` map. It cites items 9 and 10 and a
  `not_applicable` outcome for item 6.
- **`inventories/item-9.json`** — the item-9 attestation inventory (the benches
  behind the recorded results, their pins, and the cold-start command
  `scripts/cold-start-benches.sh`); **`inventories/item-9.envelope.json`** is the
  tool-produced envelope the manifest cites. Never hand-edit it.
- **`inventories/item-10.json`** — the item-10 attestation inventory
  (hygiene files and the commands CI runs); **`inventories/item-10.envelope.json`**
  is the tool-produced envelope the manifest cites. Never hand-edit it.
- **`spec-rows.json`** and **`item6-na-statement.json`** — the item-6
  `not_applicable` evidence: the ratified spec row list (one entry per table
  row of `spec/target-spec.md` §1-§7, 39 rows) and a hand-written statement
  giving each row's class and why it is deterministic or corner-bounded. The
  spec stays the source of truth; if a row changes (via a decision record),
  update both files. The manifest binds each by `content_hash`; after editing
  either, refresh the hash (`sha256sum`, prefixed `sha256:`) in
  `evidence."6".not_applicable` and regenerate the record. This says the spec
  has no statistical row; it is not an entropy or side-channel claim.
- **`design-evidence-tiers.md`** — the T1-T4 checklist the grader parses.
  Vendored **byte-identical** from
  [`2AMLogic/klayout-tools@c572046`](https://github.com/2AMLogic/klayout-tools/blob/c572046be644e0407f693f2410f3abb799d68a3a/docs/design-evidence-tiers.md)
  `docs/design-evidence-tiers.md` (the commit tag `v0.8.0` points to,
  2026-10-27; upstream is MIT-licensed, and this repo's license does not
  relicense the vendored copy). When upstream moves, re-vendor the doc and
  regenerate the record in the same PR.
- **`sky130-crypto-rot.signoff.json`** — the **verdict of record**:
  committed output of the command below. Never hand-edit it.

## Pinned tool

`klayout-tools==0.8.0` (the first release with `klt signoff --attest`).
CI, the committed record and the `KLT_VERSION` flow pin in
`scripts/setup-env.sh` all use the same release.

## Regenerate

```console
uvx --from "klayout-tools==0.8.0" klt signoff \
    --manifest manifests/sky130-crypto-rot.json \
    --tiers-doc manifests/design-evidence-tiers.md \
    --format json > manifests/sky130-crypto-rot.signoff.json
```

The command exits `3` when at least one T1 item is `unmet` (a valid, clean
run) and `0` when every item is `met`. Any change that affects the verdict
— new evidence, a manifest edit, a vendored-doc bump, a version-pin bump —
regenerates and commits the record in the same PR.

## Attest item 9

```console
uvx --from "klayout-tools==0.8.0" klt signoff --attest 9 \
    --inventory manifests/inventories/item-9.json \
    -o manifests/inventories/item-9.envelope.json
```

Runs `scripts/cold-start-benches.sh` (about 12 minutes: setup, model KATs, and the
SHA-256 (with million-`a`), AES, HMAC and key-ladder RTL
benches with their negative controls). `klt` allows one command 1800 s, so the
FORMAL key-ladder bench (`verification/formal/keyladder/run.sh`) is not in the
inventory and the `keyladder-formal` record is not covered by this attestation.
The `cold_start` command is marked `local_only`, so this re-attest runs it but
the CI envelope gate below does not (see "Freshness is CI-enforced").
Re-attest when a listed bench changes, then put the inventory's
`provenance.input.content_hash` in the manifest and regenerate the record.

## Attest item 10

```console
klt signoff --attest 10 --inventory manifests/inventories/item-10.json \
    -o manifests/inventories/item-10.envelope.json
```

The inventory's audit commands call `npm run test` and `npm run check:reuse`,
which need `pytest` on the `python3` that `klt` runs under; run `klt` from a
venv that has both (not bare `uvx`, whose `python3` has no `pytest`). The
envelope records the hashes of README.md, LICENSE and both workflows, so
re-attest after editing any of them, then put the inventory's
`provenance.input.content_hash` in the manifest and regenerate the record.
All three commands are marked `local_only`, so this re-attest runs them but the
CI envelope gate below does not (see "Freshness is CI-enforced").

## Freshness is CI-enforced

`.github/workflows/signoff.yml` runs two checks on every push to `main` and
every pull request.

**The verdict of record.** It re-runs the grader, accepts exit codes 0 and 3,
and fails when the fresh output differs byte-for-byte from the committed
record.

**The attestation envelopes.** The grade above binds items 9 and 10 only by
the hash of each inventory file, so on its own it cannot see an attested file
being edited: a PR that changes `README.md` or a listed bench without
re-attesting leaves the record byte-identical, and the stale `content_hash`
entries in the envelope go unnoticed. The step before it therefore re-checks
both envelopes with the tool's own drift mode:

```console
klt signoff --attest 9 --inventory manifests/inventories/item-9.json \
    --check manifests/inventories/item-9.envelope.json
```

and the same for item 10. That mode re-attests and writes nothing: exit `0`
only if the committed envelope still reproduces *and* still passes, `3`
otherwise, naming each field that changed. The job fails on anything but `0`
and prints the re-attest command. So the "re-attest after editing a listed
file" rule above is now mechanical rather than advisory — including for a
routine docs PR that touches the root `README.md`, which item 10 hashes.

**What the gate does not re-run.** Item 9's `cold_start` and item 10's three
audit commands are marked `local_only: true` in their inventories. `--attest`
runs them; `--attest --check` skips them, lists them under `skipped_checks`,
and carries their committed outcome into the verdict — so the gate needs no
bench toolchain and costs under a second per item, and a committed *failing*
command still fails the gate. Those commands are not left unchecked: `npm run
lint`, `npm run test` and `npm run check:reuse` are what `.github/workflows/ci.yml`
runs on the same events, and the cold start is what a re-attest runs. Because
the flag is recorded in the envelope, adding or removing it changes both the
inventory hash and the envelope.

Order of work when a PR edits `signoff.yml` itself: item 10 hashes that file,
so finish the workflow edit first and re-attest item 10 afterwards. Rebase and
re-run both `--check` commands before review — a merge to `main` that touches a
listed file in between will fail the gate.
