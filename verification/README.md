# verification

`gate-level/common/` holds a file vendored byte-identical from
`2AMLogic/sky130-modexp` at the commit pinned in
[`reuse.lock.json`](../reuse.lock.json); do not edit it here. Adoption
decisions: [`spec/decision-records/0001-modexp-tooling-adoption.md`](../spec/decision-records/0001-modexp-tooling-adoption.md).

`model/` holds the Python golden reference models (SHA-256, HMAC-SHA-256) and
`vectors/` the published known-answer vectors with provenance sidecars; see
[`model/README.md`](model/README.md). See the repo README for scope.

## What CI runs vs. what stays local

| Where | What |
|---|---|
| CI `lint` | `python3 -m compileall verification flow`; `bash -n scripts/*.sh verification/rtl/sha256/run.sh` |
| CI `model` | `pytest verification/model` over the committed SHA-256 and HMAC-SHA-256 vectors (grows as AES, KDF and DRBG models land under `model/`) |
| CI `reuse` | `check_reuse.py` re-hashes each `reuse.lock.json` file that has a local copy against its `sha256`; its self-test is `test_check_reuse.py` |
| Local only | environment provisioning, cocotb + Icarus SHA-256 core flow, synthesis, place-and-route, DRC, LVS, `klt signoff --manifest` (all need the PDK or the provisioned venv) |

CI proves format and known-answer correctness only and makes no security
claim. The pin checker and evidence-record linter are not wired yet: they are
deferred by decision record 0001 until the modexp pin moves. If a heavy leg
moves into CI, change this table, the README "Reproduce" section and
`.github/workflows/ci.yml` together.
