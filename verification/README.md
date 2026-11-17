# verification

`gate-level/common/` holds a file vendored byte-identical from
`2AMLogic/sky130-modexp` at the commit pinned in
[`reuse.lock.json`](../reuse.lock.json); do not edit it here. Adoption
decisions: [`spec/decision-records/0001-modexp-tooling-adoption.md`](../spec/decision-records/0001-modexp-tooling-adoption.md).
It still has **no caller**: the aes and sha256 `--gate-level` mode selects the
same cell models through `options.defines`, which the pinned `klt` forwards
natively, so its removal (#134) remains a decision about an uncalled file.

`model/` holds the Python golden reference models and `vectors/` the published
known-answer vectors with provenance sidecars;
[`model/README.md`](model/README.md) is the maintained list of which model is
checked against which vectors. See the repo README for scope.

## What CI runs vs. what stays local

| Where | What |
|---|---|
| CI `lint` | `python3 -m compileall verification flow`; one `bash -n` per tracked project `*.sh` (the `git ls-files` set, excluding the tool-managed `.loom/`, `.claude/`, `.agents/` and `loom.sh`); `check_pins.py` (the pins in `scripts/setup-env.sh` appear in `docs/environment.md`, agree with the `pins` block of `manifests/inventories/item-9.json`, and every hand-copied `klayout-tools` version literal in `.github/workflows/signoff.yml`, `manifests/README.md` and `README.md` equals `KLT_VERSION`); `check_regmap.py` (the register-map table in `spec/decision-records/0009-register-map.md` parses, is internally consistent, and wires no readable register to a key, seed or key-load port); `check_roadmap.py` (every `#N` status token in `docs/roadmap.md`'s `## Now` and `## Next` sections agrees with WORK_LOG.md's issue/PR records -- issue #213); `check_script_docs.py` (every `check_*.py` invoked by `npm run lint` and every `test_*.py` in `npm run test` is named in this table's `lint` and `model` rows -- issue #229) |
| CI `model` | the whole `npm run test` pytest run: `verification/model` over the committed vectors (`model/README.md` lists them), plus the checker self-tests `test_check_pins.py`, `test_check_reuse.py`, `test_record_lib.py`, `test_timing_record.py`, `test_check_regmap.py`, `test_trng_if_record.py`, `test_gen_netlist_binding.py`, `test_check_roadmap.py` and `test_check_script_docs.py` (pin resolution; the PDK-pin and dirty-input guards, and the gate-level record text, in `flow/common/record_lib.py`; the timing-input freshness guard in `flow/common/make_timing_record.py` that refuses a record whose measured inputs changed since the run -- issue #218; the register map's field-overlap and decodability rules; the TRNG interface record's skip-flag derivation; the netlist OP_GEN binding's bit order and strictness; the roadmap's `#N` status tokens against WORK_LOG.md's records; and this table's own lint/test inventory), and `test_core_flow.py` (the gate-level refusals in `flow/common/core_flow.sh`: a stale netlist, a non-`ok` synthesis, and a bench testcase declared neither run nor excluded), and `test_keyladder_formal_record.py` (the key-ladder formal record's Depth column is read from each run's `config.sby`, not from a knob -- issue #165; the flow it reports on stays local, so this is that generator's only automated check), and `test_drbg_trng_formal_record.py` (the drbg-trng formal record's `EXPECT` table is the sole judge of every `run.sh` invocation via `--check-only` -- a row that misses its expectation refuses the run, a timed-out plain-`PASS` netlist check included, and `--check-only` writes nothing -- issue #226; the flow it reports on stays local, so this is that generator's only automated check), and `test_drbg_formal_record.py` (the DRBG/TRNG formal record's mode-aware Depth rule: a run with no `config.sby`, or a bounded task whose `config.sby` names no depth, refuses to record, while a depth-less `mode prove` task records as `unbounded` -- issue #224; the flows they report on stay local, so these are those generators' only automated checks) |
| CI `reuse` | `check_reuse.py` re-hashes each `reuse.lock.json` file that has a local copy against its `sha256`; its self-test runs in `model` |
| CI `verify` | only on PRs touching `rtl/`, `verification/`, `flow/` or the env pins: `scripts/setup-env.sh`, then `scripts/ci-verify.sh` (about 8 min): the sha256, aes, drbg, hmac, keyladder, crypto_rot_top and trng_if benches and each `*_NEG_*` negative control (must fail; including `HMAC_NEG_CTRL`, `HMAC_NEG_SCRUB`, `KL_NEG_MASK`, `KL_NEG_LOCK`, `KL_NEG_ZEROIZE`, `TOP_NEG_ZEROIZE`, `TOP_NEG_FAULT`), and `verification/formal/run.sh` (its `reach_*`/`neg_*` tasks must fail) |
| CI `netlist-freshness` | only on PRs touching `rtl/`, `verification/`, `flow/` or the env pins: `scripts/setup-env.sh` (PDK-cached), then `verification/rtl/crypto_rot_top/netlist/check-fresh.sh` (issue #88): the committed crypto_rot_top gate-level netlist is re-synthesized from the RTL and byte-compared -- exit `3` on drift fails the job, so an RTL edit cannot merge without its netlist. This is the item-1 attestation's `derived` check (marked `local_only` there, where `klt signoff --check` only carries its committed outcome) |
| Local only | pre-layout setup timing (`verification/rtl/aes/run.sh --timing` and the sha256 equivalent, with or without `--record`: a single `ss_100C_1v60` corner on the synthesized netlist, so it needs the PDK and `openroad` on `$PATH`; a negative slack does not fail the run), sha256 `--million-a` (about 10 min), the aes and sha256 `--gate-level` mode (the same benches re-run on the `klt synthesize` netlist; aes about 80 s, sha256 about 28 min, and its negative control the same again), `verification/formal/keyladder` (its `neg_net` task synthesizes; over 30 min), `verification/formal/crypto_rot_top` (the P-12 structural re-proof, issue #88: two syntheses plus the mutant's, and its verdict/record are flow-local), place-and-route, DRC, LVS, `klt signoff --manifest` |

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
