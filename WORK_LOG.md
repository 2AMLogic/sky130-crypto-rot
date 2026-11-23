# Work Log

Chronological record of merged PRs and closed issues, maintained by the Guide
triage role. Entries are grouped by date, newest first.

### 2026-11-23

- **PR #310**: fix(verification): run the P-7/P-8/P-9 harness on the venv's sby and drop the closed tool-gap wording
- **Issue #129** (closed): Use the pinned SBY tools for P-7/P-8/P-9 and correct the formal record wording
- **PR #311**: fix: honor --out-dir in the crypto_rot_top P&R record generator
- **Issue #308** (closed): make_record.py accepts --out-dir and ignores it (crypto_rot_top P&R record generator)
- **PR #301**: feat: land the stage-bounded through-CTS P&R flow for crypto_rot_top
- **Issue #295** (closed): Land the crypto_rot_top place-and-route flow on main with a through-CTS record, so the route in #47 is a single off-host submit
- **PR #305**: docs: attribute the `--attest 2 --input` mint path to klayout-tools 0.9.0
- **Issue #304** (closed): manifests/README.md misattributes the `--attest 2 --input` mint path to the 0.9.2 release
- **Issue #185** (closed): Remove 15 derived klt request JSONs: each is sim-request.json plus one defines key
- **PR #299**: manifests: re-pin klayout-tools to 0.9.2 and regenerate the T1 evidence under it
- **Issue #294** (closed): Bump the klayout-tools pin from 0.8.0 to the newest PyPI release and regenerate the signoff record and envelopes

### 2026-11-18

- **PR #188**: feat(verification): run the AES and SHA-256 known-answer benches on their synthesized netlists
- **Issue #179** (closed): Run the AES and SHA-256 known-answer benches on the synthesized netlists: no gate-level simulation has been recorded for any core
- **PR #288**: test: unshadow bit-range readable-flag test in test_check_regmap.py
- **PR #286**: ci: report the required checks on merge_group commits via a fail-closed shared changed-path gate
- **PR #284**: fix: restore the strict exact-name top-module selection for the P-12 cone check
- **Issue #287** (closed): Fix shadowed duplicate test in test_check_regmap.py (bit-range flag coverage never runs)
- **Issue #281** (closed): Restore the strict exact-name top-module lookup for the P-12 cone check
- **PR #280**: refactor(formal): consolidate cone-of-influence and netlist-splice helpers into one shared module
- **Issue #277** (closed): Consolidate duplicated cone-of-influence and netlist-splice helpers in formal tooling
- **PR #275**: test: consolidate the config.sby reader contract into test_record_lib.py
- **PR #195**: refactor(verification): drop the dead collection() full param and share cycles/check in trng_if benches
- **Issue #263** (closed): Consolidate the config.sby reader tests: one contract in test_record_lib.py instead of three generator suites (one run 3x)
- **Issue #182** (closed): Remove the dead `full` parameter from the trng_if bench's collection(): the two tests pass False/True to a parameter the body never reads

### 2026-11-17

- **PR #272**: docs: correct T1 item-10 envelope count to three (items 1, 9, 10)
- **PR #270**: docs: sync roadmap T1 table and blocked note with the committed signoff manifest
- **Issue #271** (closed): docs/roadmap.md T1 item-10 row says CI re-hashes "both envelopes"; it now re-checks three
- **Issue #269** (closed): docs/roadmap.md's T1 table says item 1 unmet / 2 of 11 met, but the committed signoff record grades item 1 met with 3 met
- **PR #267**: netlist: commit the crypto_rot_top netlist with freshness check and P-12 structural re-proof
- **PR #265**: chore(loom): resync installed Loom to v0.19.1306
- **PR #264**: test: pin the mode reader and steps scrape to the shared record_lib readers
- **PR #261**: fix: consolidate sby_mode and the steps scrape into record_lib's shared readers
- **PR #258**: docs: correct sby_depth's docstring after the mode-aware depth rule
- **PR #257**: fix: name the two sby_mode None cases in the formal record refusal
- **PR #196**: top: crypto_rot_top behind the 0005 bus, 0009 register map and the section 5 lifecycle FSM
- **Issue #88** (closed): T1 item 1 (b): crypto_rot_top netlist, freshness check, netlist re-proof of P-12 and --attest 1
- **Issue #46** (closed): T1 item 1 (design sources): top-level integration, Wishbone registers, lifecycle FSM, sky130 netlist, --attest 1
- **Issue #262** (closed): Extend the one-parser identity guard to sby_mode and sby_steps_checked
- **Issue #259** (closed): Consolidate sby_mode and the steps_checked scrape into record_lib: a second config.sby reader re-grew after #211
- **Issue #255** (closed): flow/common/record_lib.py sby_depth docstring is stale after #224's mode-aware Depth rule
- **Issue #243** (closed): sby_mode() collapses "no config.sby" and "config.sby with no mode line", and the refusal names only the first
- **Issue #87** (closed): T1 item 1 (a): crypto_rot_top RTL, register interface, lifecycle/zeroize FSM and bus-level bench
- **PR #242**: fix: share one sby_depth reader so the formal generator honors commented section headers
- **Issue #221** (closed): verification/formal/make_record.py has the same raw-line sby header match #194 fixed in the keyladder reader
- **PR #253**: fix: strip and case-fold Ports tokens in check_regmap key-port lint
- **PR #239**: formal: make the DRBG/TRNG record's Depth verdict mode-aware
- **Issue #236** (closed): check_regmap.py key-port lint: residual token-hygiene evasions (trailing space, case, nested bit ranges)
- **Issue #224** (closed): DRBG/TRNG formal generator records a run whose config.sby names no depth; the keyladder judge fails it

### 2026-11-16

- **PR #237**: chore(loom): resync installed Loom to v0.19.1302
- **PR #251**: docs: state the load-bearing reverse-assertion rationale in check_script_docs.py
- **PR #249**: docs: record check_script_docs.py's one-directional design in its docstring
- **Issue #250** (closed): check_script_docs.py docstring: the two cited prose mentions do not demonstrate reverse-assertion unsafety
- **Issue #235** (closed): check_script_docs.py is one-directional: a stale filename left in the CI table is not flagged
- **PR #227**: lint: check docs/roadmap.md #N status tokens against WORK_LOG.md in npm run lint
- **Issue #213** (closed): docs/roadmap.md status lines drift within hours: make the #N claims checked in CI rather than re-measured by hand
- **PR #246**: docs(manifests): document the toolchain-free --skip-local-only item-9 re-attest route
- **PR #245**: test: make the check-only tripwire drop an untracked stray, not a spec write
- **PR #238**: test: pin the drbg-trng formal EXPECT judge (--check-only) like its keyladder sibling
- **PR #234**: test(formal): pin opgen_binding classifies uppercase X/Z as undriven
- **PR #233**: fix: see through bit-range port spellings in the regmap key-port lint
- **PR #232**: checkers: derive the CI-table lint/test inventory from package.json
- **PR #228**: timing: stamp each run's measured inputs and refuse stale scratch at record time
- **PR #225**: formal: validate op_q probe tokens whole; die outside 01xXzZ
- **PR #223**: formal: keep PROVE_DEPTH off the P-5 negative controls
- **PR #220**: fix(formal): judge every run with make_record.py's EXPECT, not a bash copy
- **PR #216**: refactor: share one sby_depth config.sby reader between both formal generators
- **PR #214**: fix: mirror sby's mode-conditional comment strip in the sby_depth header match
- **PR #203**: refactor(verification): one option parser, one evidence definition, one summaries helper
- **PR #198**: lint: fold check_regmap into npm run lint and add the engine-side key ports to its denylist
- **Issue #241** (closed): test_drbg_trng_formal_record.py's check-only tripwire writes into the shared checkout (spec/key-isolation-properties.md)
- **Issue #240** (closed): manifests/README.md does not document the --skip-local-only route for re-attesting item 9 on a host without the bench toolchain
- **Issue #230** (closed): formal: pin that opgen_binding treats uppercase X/Z as undriven (#219 test-plan item b)
- **Issue #229** (closed): The lint/test inventory in README.md and verification/README.md is hand-maintained and omits check_roadmap.py
- **Issue #226** (closed): formal: the drbg-trng EXPECT judge is now the sole verdict for every run but has no committed test (the sibling keyladder judge does)
- **Issue #219** (closed): formal: gen_netlist probe regex can silently truncate an unexpected op_q character (uppercase Z)
- **Issue #218** (closed): make_timing_record.py can stamp one core's stale timing run with another revision: tie flow/build/<core>/sta.json to the revision that produced it
- **Issue #215** (closed): check_regmap.py key-port denylist is evaded by a bit-range port spelling (`aes_key[127:0]`)
- **Issue #211** (closed): Dedupe sby_depth: identical config.sby reader copied across both formal generators
- **Issue #210** (closed): keyladder formal: PROVE_DEPTH below 9 turns the P-5 negative controls UNKNOWN and fails the flow verdict (no record written)
- **Issue #207** (closed): formal netlist: run.sh's reached-depth leniency also swallows a timed-out negative control, so a vacuity check that never ran exits 0
- **Issue #194** (closed): keyladder record: sby_depth() matches a section header before stripping its trailing comment, unlike sby itself
- **Issue #193** (closed): Follow-up on 0009 register-map lint: CI wiring, README enumerations, key-port denylist
- **Issue #186** (closed): Finish the core_flow.sh convergence: six copies of the run.sh option parser, two of the negative-control evidence pattern

### 2026-11-15

- **PR #217**: formal: index the netlist op_q probe binding from the LSB end
- **Issue #206** (closed): formal netlist: gen_netlist.py binds the op_q probe pattern with an inverted bit index
- **PR #197**: feat: pre-layout setup-timing mode for aes_core and sha256_core (klt sta at ss_100C_1v60, 20 ns)
- **Issue #178** (closed): First timing measurement: record pre-layout setup slack for aes_core and sha256_core at ss_100C_1v60 against the 20 ns clock
- **PR #199**: docs: roadmap as of 2026-11-15 at a1b3ae1; rename to docs/roadmap.md, link from README
- **Issue #181** (closed): docs/ROADMAP.md: fix the 'cores landed' date, refresh three moved status lines, link it from README
- **PR #209**: fix(verification): trng_if record names the real skip flag; cite spec 3.4
- **Issue #202** (closed): trng_if bench: wrong spec cross-reference (3.2 should be 3.4) and a --skip-real record naming the wrong skip flag
- **PR #205**: formal: re-prove P-7/P-8/P-9 on the klt synthesize sky130_fd_sc_hd netlist (run.sh --netlist)
- **Issue #177** (closed): Re-prove P-7, P-8 and P-9 on the synthesized netlist: the spec marks all three netlist-provable and the record covers RTL only
- **Issue #169** (closed): Live run of verification/formal/keyladder/run.sh to confirm #165's depth reader against real sby work directories
- **PR #201**: refactor(rtl): drop the never-driven ack_q declaration from drbg_top
- **PR #190**: feat(verification): simulate the pinned TRNG sibling at its own parameters
- **Issue #192** (closed): Remove the dead ack_q register from drbg_top.v: declared beside two live flops, never driven or read since its first commit
- **Issue #180** (closed): Run drbg_top against sky130-trng's RTL at its unshortened parameters: the real-sibling bench shortens start-up and the conditioner block
- **PR #200**: refactor(verification): parse setup-env.sh's pin block once, in record_lib.parse_pins
- **Issue #189** (closed): Collapse the two parsers of setup-env.sh's pin block: record_lib.pin() ignores the block bounds, and the pin-name list is hand-copied three ways

### 2026-11-14

- **PR #184**: feat(verification): check hand-copied klt version literals against KLT_VERSION
- **PR #175**: refactor(verification): derive each negative control from its positive request
- **PR #170**: refactor: read the keyladder formal record's Depth column from each run's config.sby
- **PR #90**: spec: add register map decision record 0009 with table lint
- **Issue #172** (closed): check_pins.py still leaves the klayout-tools pin hand-copied in signoff.yml and manifests/README.md
- **Issue #165** (closed): Read the key-ladder formal record's Depth column from sby's config.sby: it is hand-copied five ways, and PROVE_DEPTH mislabels three P-6 rows
- **Issue #163** (closed): manifests: item-9 inventory does not cover flow/common/core_flow.sh, the shared bench driver all six run.sh scripts source
- **Issue #161** (closed): Remove the 12 hand-copied negative-control request files: each is its positive request plus one define, so derive them at run time
- **Issue #89** (closed): Spec: register map decision record (offsets, access types, STATUS layout, key-load window) for crypto_rot_top
- **PR #176**: docs: roadmap as of 2026-11-13
- **PR #171**: feat(verification): check the item-9 inventory's pins against setup-env.sh and re-attest
- **Issue #164** (closed): Bring the item-9 inventory's hand-copied tool pins under check_pins.py: its klayout-tools pin is still the git revision setup-env.sh dropped on 2026-10-27
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
