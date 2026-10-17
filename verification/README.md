# verification

`gate-level/common/` holds a file vendored byte-identical from
`2AMLogic/sky130-modexp` at the commit pinned in
[`reuse.lock.json`](../reuse.lock.json); do not edit it here. Adoption
decisions: [`spec/decision-records/0001-modexp-tooling-adoption.md`](../spec/decision-records/0001-modexp-tooling-adoption.md).

`model/` holds the Python golden reference models (SHA-256, HMAC-SHA-256) and
`vectors/` the published known-answer vectors with provenance sidecars; see
[`model/README.md`](model/README.md). See the repo README for scope.
