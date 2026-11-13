#!/usr/bin/env bash
#
# scripts/cold-start-benches.sh -- the T1 item 9 cold-start command: from a clean
# checkout, provision the pinned environment and run every testbench that backs a
# result in verification/records/, except the one named below.
#
#   ./scripts/cold-start-benches.sh
#
# Exit 0 only if every step exits 0. Each RTL run.sh exits 0 only if its simulation
# passed and synthesis is ok; each --negative-control run exits 0 only if the bench
# CAUGHT the injected fault, so a control is a control, not a pass claim.
# verification/formal/run.sh exits 0 only if every SymbiYosys task met its
# expectation, which for its reach_*/neg_* tasks means FAILING.
#
# Records this covers: sha256-core-sim-synth, aes-core-sim-synth, drbg-sim-synth,
# hmac-sha256-sim-synth, keyladder-sim-synth, trng-if-sim, drbg-trng-formal.
#
# Records this does NOT cover, and why:
#   * keyladder-formal -- verification/formal/keyladder/run.sh. Its bounded
#     module-boundary P-1 runs are allowed 1500 s each (P1_TIMEOUT_S), which
#     exceeds the 1800 s `klt signoff --attest` allows one command. Run that
#     bench by hand; its header gives the command.
#   * smoke-synthesis-sim -- retired. Its bench (flow/smoke/) is no longer in
#     the tree, so the record is history, not a reproducible claim.
#   * independent-rerun -- not a bench of its own: re-runs of the flows above.
#
# Prerequisite beyond ./scripts/setup-env.sh: the trng_if bench fetches the
# sibling's RTL at its pinned commit with `gh api`
# (verification/rtl/trng_if/fetch_trng.sh), so a GitHub credential must be in the
# environment (`gh auth login`, or GH_TOKEN) for this script to run start to
# finish. Without one, run `verification/rtl/trng_if/run.sh --skip-real` by hand
# instead; the stub benches still run, and the real-sibling half of the
# trng-if-sim record is then not covered.
#
# Wall time is about 18 minutes, dominated by the SHA-256 million-`a` KAT
# (1092 s measured for the `klt signoff --attest 9` run that produced the
# committed envelope, against the 1800 s that command allows).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

./scripts/setup-env.sh
# pytest for the model and reuse checks; the same package CI installs.
.venv/bin/python -m pip install --quiet pytest

.venv/bin/python -m pytest verification/model
.venv/bin/python verification/check_reuse.py
.venv/bin/python -m pytest verification/test_check_reuse.py

for core in sha256 aes drbg hmac keyladder trng_if; do
  if [ "${core}" = sha256 ]; then
    ./verification/rtl/sha256/run.sh --million-a
  else
    ./verification/rtl/${core}/run.sh
  fi
  ./verification/rtl/${core}/run.sh --negative-control
done

./verification/formal/run.sh
