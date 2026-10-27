#!/usr/bin/env bash
#
# scripts/cold-start-benches.sh -- the T1 item 9 cold-start command: from a clean
# checkout, provision the pinned environment and run every testbench that backs a
# result in verification/records/ (except the FORMAL bench, see below).
#
#   ./scripts/cold-start-benches.sh
#
# Exit 0 only if every step exits 0. Each RTL run.sh exits 0 only if its simulation
# passed and synthesis is ok; each --negative-control run exits 0 only if the bench
# CAUGHT the injected fault, so a control is a control, not a pass claim.
#
# Not run here: verification/formal/keyladder/run.sh. Its bounded module-boundary P-1
# runs are allowed 1500 s each, which exceeds the 1800 s `klt signoff --attest`
# allows one command. The record keyladder-formal is therefore not backed by this
# attestation; run that bench by hand (its header gives the command).
#
# Wall time is about 15 minutes, dominated by the SHA-256 million-`a` KAT.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

./scripts/setup-env.sh
# pytest for the model and reuse checks; the same package CI installs.
.venv/bin/python -m pip install --quiet pytest

.venv/bin/python -m pytest verification/model
.venv/bin/python verification/check_reuse.py
.venv/bin/python -m pytest verification/test_check_reuse.py

./flow/smoke/run.sh
for core in sha256 aes hmac keyladder; do
  if [ "${core}" = sha256 ]; then
    ./verification/rtl/sha256/run.sh --million-a
  else
    ./verification/rtl/${core}/run.sh
  fi
  ./verification/rtl/${core}/run.sh --negative-control
done
