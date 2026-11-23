# 0010 - Remove the vendored design-evidence tiers doc

Status: Accepted. Date: 2026-11-23.

## Decision

The T1-T4 design-evidence checklist `klt signoff` grades against is the
copy bundled with the pinned klayout-tools release alone. The repo keeps no
vendored copy of `docs/design-evidence-tiers.md` and no `--tiers-doc`
override: every caller (`manifests/README.md`, `README.md`,
`.github/workflows/signoff.yml`) invokes the grader without it. This
records the reversal of the earlier decision to vendor the document
(made in issue #121's proposal premise and carried in `manifests/README.md`
until now), per the operator ruling of 2026-11-23 (attended
`/fleet:decide` session, round 20261121-r19, q103), issued once for the
twelve repos that asked the same question: *"remove the vendored copy of
the design-evidence tiers document and the `--tiers-doc` override. The
pinned klayout-tools release alone selects the checklist."*

The checklist is therefore read at
[`docs/design-evidence-tiers.md` at tag `v0.9.2`](https://github.com/2AMLogic/klayout-tools/blob/v0.9.2/docs/design-evidence-tiers.md)
upstream. It changes only through a klayout-tools pin bump, and the
existing CI comparison — a fresh `klt signoff` run byte-compared against
the committed `manifests/sky130-crypto-rot.signoff.json` — is what catches
a checklist change at a pin bump. That comparison stays.

## Alternatives rejected

- **Keep a `--tiers-doc` override "just in case"**: the ruling removes it.
  An override with no vendored doc has no caller and reopens the drift the
  ruling closes.
- **Keep vendoring byte-identical at each pin bump**: a second copy that
  can drift from the pinned tool and costs a re-vendor step on every bump,
  for no grading benefit the pinned wheel does not already provide.

## Consequences

- No spec row changes; this record touches process only.
- A klayout-tools pin bump now regenerates the signoff record (the
  checklist may have moved with the release) but no longer re-vendors a
  document.
- `manifests/sky130-crypto-rot.signoff.json` records
  `source_doc: docs/design-evidence-tiers.md` — the wheel-bundled path —
  where it previously recorded `manifests/design-evidence-tiers.md`.
  The source-document content hash and every item verdict are unchanged by
  this reversal; a verdict change at regeneration would have stopped the
  change per the ruling.
- `verification/check_pins.py` still pins the release tag
  `manifests/README.md` cites against `KLT_VERSION`, so a bump that misses
  the upstream link fails the lint gate.
