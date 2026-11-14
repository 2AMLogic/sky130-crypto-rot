# Work Log

Chronological record of merged PRs and closed issues, maintained by the Guide
triage role. Entries are grouped by date, newest first.

### 2026-11-14

- **PR #162**: fix(verification): make every negative control prove the bench caught the fault
- **Issue #151** (closed): Run the drbg, trng_if and sha256-scrub negative controls through core_flow_negctl_one: three hand-rolled copies remain, and the drbg one counts any klt failure as caught

### 2026-11-13

- **PR #168**: docs: replace environment.md's SHA-256-only flow text with pointers to the maintained lists
- **PR #166**: refactor: give run.sh a --sim-only mode and drop ci-verify's own bench list
- **PR #152**: refactor: drive the drbg record from record_lib.main(), build the klt-provenance bullet once
- **PR #157**: refactor(records): derive each generator's own-directory inputs from git
- **PR #160**: chore: drop the analog-template .gitignore rules, re-ignoring flow report logs
- **PR #156**: docs: drop the stale per-core status lists from README.md
- **PR #154**: docs(keyladder): drop the scrubbed-datapath limitation from the record generators
- **PR #153**: docs: correct inherited upstream text in setup-env.sh
- **PR #155**: refactor: add setup-env.sh to record inputs by name, not by position
- **PR #148**: chore(manifests): cover the 8 unlisted klt request files in item 9
- **PR #145**: test(cold-start): cover the drbg, trng_if and P-7/P-8/P-9 benches and re-attest item 9
- **PR #142**: feat(records): derive `supersedes` from the tracked record trail
- **PR #139**: chore(trng_if): stop tracking the klt requests mk_req.py rewrites every run
- **PR #140**: ci: fail signoff when an item 9 or 10 attestation envelope goes stale
- **PR #132**: lint: derive the bash -n set from git ls-files, one file per invocation
- **PR #135**: fix(manifests): re-attest item-10 envelope so hygiene hashes match main
- **PR #128**: refactor: add the shared flow helpers to record inputs in record_lib, not per core
- **PR #126**: ci: run the pin and record-lib checker self-tests from the model job
- **Issue #167** (closed): Remove the SHA-256-only flow description from docs/environment.md: three passages predate the other five cores, and one cites a PATH export that run.sh does not contain
- **Issue #158** (closed): Remove the hand-kept positive-simulation list from scripts/ci-verify.sh: give run.sh a --sim-only mode so CI runs each core's own list
- **Issue #141** (closed): Move drbg/make_record.py onto record_lib.main(): last hand-rolled sim+synth record driver, and it records pinned instead of measured tool versions
- **Issue #146** (closed): Derive record generators' own-directory inputs instead of hand-listing them: 67 lines in eight generators, and hmac already misses a request file
- **Issue #159** (closed): Remove the analog-template rules from .gitignore: they describe an ngspice sim tree this repo never had, and one un-ignores every log under a flow's reports directory
- **Issue #147** (closed): Remove the hand-kept per-core status lists from README.md: all three say only SHA-256 exists, and rtl/README.md already carries the current list
- **Issue #149** (closed): Remove the fixed 'hmac clear does not clear the SHA-256 datapath' limitation from the key-ladder record generators: RTL has scrubbed it since a77caa3, and the next --record would write it as evidence
- **Issue #143** (closed): setup-env.sh carries upstream leftovers: issue refs #141/#143 that point at unrelated issues here, another design's slack figure in a FATAL message, and a usage line the parser rejects
- **Issue #138** (closed): Remove the positional setup-env.sh convention from record generators: applied three ways, and three record families never hash it
- **Issue #144** (closed): item-9 inventory omits the sha256 and hmac scrub request files that the cold start runs
- **Issue #131** (closed): cold-start-benches.sh says it runs every bench behind a record but skips drbg, trng_if and the P-7/P-8/P-9 formal run; item 9 is attested on 4 of 6 RTL benches
- **Issue #137** (closed): Records always say 'Supersedes: none': the field is hardcoded at 6 sites while 7 of 16 records re-run an earlier one; derive it in write_record()
- **Issue #136** (closed): trng_if bench tracks eight request files that run.sh regenerates from mk_req.py on every run: keep the generator, untrack its output
- **Issue #133** (closed): Attestation envelopes go stale silently: no CI check re-hashes them (item 9 drifted again after #93, item 10 within a day)
- **Issue #127** (closed): lint: bash -n checks 1 of 13 tracked scripts; ci.yml header names 4 of 6 benches
- **Issue #130** (closed): item-10 attestation envelope hashes for README.md and ci.yml differ from the tree on main
- **Issue #124** (closed): Define shared flow helpers in record INPUTS once: core_flow.sh/record_lib.py are hashed in some cores, missing in others
- **Issue #122** (closed): Wire test_record_lib.py and test_check_pins.py into CI: 13 tests no job runs

### 2026-11-12

- **PR #119**: Bump Repo Skills 0.25.10 -> 0.26.1

### 2026-11-07

- **PR #117**: Bump Repo Skills 0.25.1 -> 0.25.10

### 2026-11-06

- **PR #115**: test: run hmac and keyladder benches and negative controls in ci-verify
- **Issue #114** (closed): Add the hmac and keyladder benches and their negative controls to scripts/ci-verify.sh

### 2026-11-01

- **PR #110**: Bump Repo Skills 0.24.7 -> 0.25.1

### 2026-10-31

- **PR #109**: refactor: record_lib.main reuses write_record; hmac and keyladder use main
- **Issue #103** (closed): Finish record_lib convergence: main() reuses write_record; hmac/keyladder use main()
- **PR #106**: docs: independent drbg, trng_if and formal re-run records with CI demo evidence
- **PR #99**: test: independent re-run records and CI verify job for benches, negative controls and formal
- **Issue #85** (closed): Independently re-run the verification flows behind #65, #66 and #69, and add them to CI

### 2026-10-30

- **PR #102**: refactor: run hmac, keyladder, drbg and trng_if scripts on core_flow.sh
- **PR #101**: refactor: converge hmac, keyladder rtl and formal record makers on record_lib
- **PR #96**: fix: connect hmac_sha256 clear to sha256_core scrub and test core zeroization
- **PR #95**: refactor: converge record makers on flow/common/record_lib.py
- **PR #93**: fix: re-attest item 9 envelope to match benches on main
- **PR #66**: refactor(verification): share record and driver scaffolding across core flows
- **PR #65**: feat(rtl): add scrub input to sha256_core clearing w, hh and a-h
- **PR #40**: chore: retire the adder smoke flow in favour of the SHA-256 core flow
- **Issue #100** (closed): Converge hmac, keyladder, drbg, trng_if run.sh on flow/common/core_flow.sh
- **Issue #98** (closed): bug: record_common.py reads removed KLT_REV pin, --record fails for drbg, trng_if, formal
- **Issue #97** (closed): Converge remaining record makers (hmac, rtl/keyladder, formal/keyladder) on record_lib
- **Issue #91** (closed): Converge flow/common/record_lib.py and verification/rtl/record_common.py into one record helper
- **Issue #63** (closed): hmac_sha256: drive sha256_core scrub from clear/zeroize
- **Issue #92** (closed): item-9 attestation envelope hashes for sha256 run.sh/test_sha256_core.py differ from the tree on main
- **Issue #64** (closed): Dedupe record-generation scaffolding shared by the aes and sha256 verification flows
- **Issue #61** (closed): sha256_core reset leaves w/hh/a-h intact; hmac_sha256 clear does not scrub key-derived hash state
- **Issue #36** (closed): Retire the adder smoke flow: superseded by the SHA-256 core flow

### 2026-10-29

- **PR #69**: feat(rtl): CTR_DRBG core and TRNG interface with benches and P-7/P-8/P-9 formal
- **Issue #45** (closed): T1 item 1 (design sources): CTR_DRBG (AES-128, df) and sky130-trng interface RTL, with SP 800-90A KATs

### 2026-10-28

- **PR #81**: feat(verification): add pin-sync checker and wire it into lint
- **Issue #80** (closed): Pin-sync checker is claimed in setup-env.sh and environment.md but does not exist

### 2026-10-27

- **PR #78**: build(env): pin klayout-tools to PyPI 0.8.0 instead of a git revision
- **Issue #77** (closed): Bump klayout-tools pin dac2b5daceb6 → 0.8.0
- **PR #75**: feat(manifests): attest T1 item 9 with a bench inventory and cold-start script
- **Issue #52** (closed): T1 item 9 (testbenches shipped): testbench inventory and klt signoff --attest 9
- **PR #73**: feat(manifests): record signoff item 6 as not_applicable
- **Issue #51** (closed): T1 item 6 (statistical claims): hash-bound not_applicable statement covering every ratified spec row
- **Issue #44** (closed): T1 item 1 (design sources): HMAC-SHA-256, SP 800-108 key ladder and key-slot RTL, with KATs and FORMAL
- **PR #71**: feat(verification): formal P-5, P-6, P-2 and module-boundary P-1 for the key ladder
- **Issue #56** (closed): T1 item 1 (design sources): SymbiYosys properties P-5, P-6, P-2 and module-boundary P-1 for the key ladder
- **PR #57**: docs(manifests): pin klayout-tools 0.8.0 and attest T1 item 10
- **Issue #42** (closed): T1 item 10 (repo hygiene): bump the signoff klt pin to one with --attest, fix README status, attest item 10
- **PR #68**: feat(rtl): key ladder with use-mask, lock, KDF sequencer and zeroize
- **Issue #55** (closed): T1 item 1 (design sources): key ladder RTL — SP 800-108 KDF sequencer, 4 slots, use-masks, locks, zeroize
- **PR #62**: feat(rtl): AES-128 encrypt/decrypt core with cocotb bench, vectors and record
- **Issue #43** (closed): T1 item 1 (design sources): AES-128 encrypt/decrypt core RTL, one round per cycle, with FIPS 197 KAT bench
- **PR #58**: feat(rtl): add HMAC-SHA-256 sequencer around sha256_core
- **Issue #54** (closed): T1 item 1 (design sources): HMAC-SHA-256 RTL around sha256_core, RFC 4231 KATs (incl. long keys)

### 2026-10-23

- **PR #34**: ci: grade T1 evidence tier with a committed klt signoff record
- **Issue #32** (closed): T1 item 10: commit a klt signoff block manifest, vendored checklist and signoff CI job as the verdict of record
- **PR #35**: feat(rtl): SHA-256 hash core with KAT bench, negative control and synthesis record
- **Issue #33** (closed): RTL: SHA-256 core (one round per cycle, hardware padding, 32-bit byte counter) with a cocotb KAT bench against verification/model/sha256.py

### 2026-10-22

- **PR #18**: ci: add lint, model and reuse CI jobs with real npm check scripts
- **Issue #7** (closed): CI skeleton: lint, reference-model tests and evidence-format checks on every PR

### 2026-10-21

- **PR #27**: Bump Repo Skills 0.24.3 -> 0.24.7

### 2026-10-18

- **PR #22**: feat(verification): add CTR_DRBG golden model with CAVP vectors
- **Issue #16** (closed): Golden model: CTR_DRBG (SP 800-90A) with CAVP DRBG vectors
- **PR #19**: feat(verification): SP 800-108 counter-mode HMAC-SHA-256 KDF model with CAVP vectors
- **Issue #12** (closed): Golden model: SP 800-108 counter-mode KDF over HMAC-SHA-256 (CAVP KBKDF vectors)
- **PR #20**: feat(verification): add FIPS 197 AES-128 golden model with vectors
- **Issue #11** (closed): Golden model: AES block (FIPS 197 vectors)
- **PR #15**: docs(spec): fix HMAC cost, P-number citations and bus-fault list
- **Issue #14** (closed): spec: fix three small inconsistencies found reviewing the v1 spec (PR #10)
- **Issue #5** (closed): Golden reference model and known-answer vectors for AES-128, SHA-256/HMAC, KDF and CTR_DRBG

### 2026-10-17

- **PR #13**: feat: add SHA-256 and HMAC-SHA-256 golden models with provenance-checked vectors
- **PR #10**: docs(spec): ratify v1 target spec, TRNG interface and isolation properties
- **PR #9**: feat: pinned toolchain provisioner and adder smoke flow with run record
- **PR #8**: feat: pin sky130-modexp and vendor three reusable flow/LVS/sim files
- **PR #1**: chore(loom): Install Loom 0.19.1180
- **Issue #6** (closed): Port of sky130-modexp's digital flow and verification harness: adopt or record
- **Issue #4** (closed): Pin the sky130A PDK and digital toolchain, and commit a smoke synthesis + simulation run
- **Issue #2** (closed): Draft and ratify the target spec
