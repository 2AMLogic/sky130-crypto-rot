# Work Log

Chronological record of merged PRs and closed issues, maintained by the Guide
triage role. Entries are grouped by date, newest first.

### 2026-10-23

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
