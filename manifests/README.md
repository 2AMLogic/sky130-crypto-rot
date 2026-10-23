# Block manifest and tier-verdict record

This directory holds this block's `klt signoff` input and its committed
output, so the gap to the klayout-tools T1 checklist is read from a tool
rather than from prose.

## Files

- **`sky130-crypto-rot.json`** — the block manifest: `block`,
  `kind: digital`, and an `evidence` map. The map is deliberately empty:
  no item cites evidence yet.
- **`design-evidence-tiers.md`** — the T1-T4 checklist the grader parses.
  Vendored **byte-identical** from
  [`2AMLogic/klayout-tools@0e2362b`](https://github.com/2AMLogic/klayout-tools/blob/0e2362bda7309829398a35d54efaa989d5806065/docs/design-evidence-tiers.md)
  `docs/design-evidence-tiers.md` (the commit tag `v0.7.0` points to,
  2026-10-23; upstream is MIT-licensed, and this repo's license does not
  relicense the vendored copy). When upstream moves, re-vendor the doc and
  regenerate the record in the same PR.
- **`sky130-crypto-rot.signoff.json`** — the **verdict of record**:
  committed output of the command below. Never hand-edit it.

## Pinned tool

`klayout-tools==0.7.0` (the latest PyPI release when this was committed).
CI and the committed record use the same pin. This pin is independent of the
`KLT_REV` flow pin in `scripts/setup-env.sh`; the two need not match.

## Regenerate

```console
uvx --from "klayout-tools==0.7.0" klt signoff \
    --manifest manifests/sky130-crypto-rot.json \
    --tiers-doc manifests/design-evidence-tiers.md \
    --format json > manifests/sky130-crypto-rot.signoff.json
```

The command exits `3` when at least one T1 item is `unmet` (a valid, clean
run) and `0` when every item is `met`. Any change that affects the verdict
— new evidence, a manifest edit, a vendored-doc bump, a version-pin bump —
regenerates and commits the record in the same PR.

## Freshness is CI-enforced

`.github/workflows/signoff.yml` re-runs the grader on every push to `main`
and every pull request, accepts exit codes 0 and 3, and fails when the
fresh output differs byte-for-byte from the committed record.
