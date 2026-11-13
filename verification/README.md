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
| CI `lint` | `python3 -m compileall verification flow`; one `bash -n` per tracked project `*.sh` (the `git ls-files` set, excluding the tool-managed `.loom/`, `.claude/`, `.agents/` and `loom.sh`); `check_pins.py` (the pins in `scripts/setup-env.sh` appear in `docs/environment.md`) |
| CI `model` | the whole `npm run test` pytest run: `verification/model` over the committed SHA-256 and HMAC-SHA-256 vectors (grows as AES, KDF and DRBG models land under `model/`), plus the checker self-tests `test_check_pins.py`, `test_check_reuse.py` and `test_record_lib.py` (pin resolution and the PDK-pin and dirty-input guards in `flow/common/record_lib.py`) |
| CI `reuse` | `check_reuse.py` re-hashes each `reuse.lock.json` file that has a local copy against its `sha256`; its self-test runs in `model` |
| CI `verify` | only on PRs touching `rtl/`, `verification/`, `flow/` or the env pins: `scripts/setup-env.sh`, then `scripts/ci-verify.sh` (about 8 min): the sha256, aes, drbg, hmac, keyladder and trng_if benches and each `*_NEG_*` negative control (must fail; including `HMAC_NEG_CTRL`, `HMAC_NEG_SCRUB`, `KL_NEG_MASK`, `KL_NEG_LOCK`, `KL_NEG_ZEROIZE`), and `verification/formal/run.sh` (its `reach_*`/`neg_*` tasks must fail) |
| Local only | synthesis, sha256 `--million-a` (about 10 min), `verification/formal/keyladder` (its `neg_net` task synthesizes; over 30 min), place-and-route, DRC, LVS, `klt signoff --manifest` |

Dated evidence that `verify` behaves as the table says (throwaway draft PRs,
closed unmerged, 2026-10-31, against `70b0a85`):

- Red when a negative control stops failing: PR #104 disabled `AES_NEG_CTRL` in
  `rtl/aes/aes_core.v`; `verify` failed with `FAIL: the bench passed with a
  corrupted S-box`
  ([run 41151370459](https://github.com/2AMLogic/sky130-crypto-rot/actions/runs/41151370459/job/124388432839)).
- Docs-only skips the work: PR #105 touched only `docs/environment.md`; the
  `verify` job reported success with setup-python, apt, cache, `setup-env.sh` and
  `ci-verify.sh` all skipped
  ([run 41151373181](https://github.com/2AMLogic/sky130-crypto-rot/actions/runs/41151373181/job/124388440094)).

CI proves format, known-answer correctness and that the benches and formal
tasks catch their negative controls; it makes no security claim. `verify`
records nothing: records stay Builder- or re-run-produced under
`verification/records/`. The evidence-record linter is not wired yet: it is
deferred by decision record 0001 until the modexp pin moves. If a heavy leg
moves into CI, change this table, the README "Reproduce" section and
`.github/workflows/ci.yml` together.

## What a record's `supersedes` field asserts

`flow/common/record_lib.py` fills a new record's `supersedes` in from the tree:
it names the newest record git already tracks for the same experiment, or
`none` when the experiment has none. Nobody types the value.

It asserts exactly one thing: the named record is the **previous** record of
this experiment and is, from here on, frozen history rather than a claim about
current sources. It does **not** assert that the new record repeats or widens
every check the old one made -- what a record covers is stated by its own
Claim and Result bullets, and a narrower re-run still supersedes the record it
follows (the SHA-256 trail alternates on the `--million-a` KAT, for instance).
Records are append-only, so the chain is never edited afterwards: the records
written before this field worked stay unlinked.
