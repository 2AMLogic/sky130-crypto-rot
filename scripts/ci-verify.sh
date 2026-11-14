#!/usr/bin/env bash
#
# scripts/ci-verify.sh -- the cheapest subset of the local verification flows
# that still trips every negative control (issue #85). CI runs exactly this.
#
#   ./scripts/setup-env.sh                  # once: .venv, pinned yosys, PDK
#   ./scripts/ci-verify.sh
#
# Covers sha256, aes, drbg, hmac, keyladder and trng_if. Per core, both halves
# come from that core's own run.sh: `--sim-only` runs its positive
# simulation(s) and stops before synthesis, `--negative-control` runs every
# control, which must FAIL (the run.sh exits non-zero if one passes). Which
# simulations a core has is the run.sh's business alone -- this script never
# keeps a second list of them, so a bench added there is run here too (#114,
# #131). Then the SymbiYosys tasks, whose reach_*/neg_* tasks must fail.
# Nothing is recorded.
#
# Left out, on purpose, and named in verification/README.md:
#   * synthesis (needs the PDK and is not a property check);
#   * sha256 --million-a (about 10 min of Icarus);
#   * verification/formal/keyladder (its neg_net task synthesizes and runs a
#     gate-level BMC; over half an hour locally).
# A pass here is a correctness and bench-sensitivity claim, nothing more.
#
# The sibling's RTL for the trng_if bench is fetched with `gh api`; set
# GH_TOKEN (CI passes github.token).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ ! -x "${REPO_ROOT}/.venv/bin/klt" ]; then
  echo "error: ${REPO_ROOT}/.venv is not provisioned; run ./scripts/setup-env.sh first." >&2
  exit 1
fi
export PATH="${REPO_ROOT}/.venv/bin:${PATH}"

for core in sha256 aes drbg hmac keyladder; do
  echo "== simulations: $core =="
  "${REPO_ROOT}/verification/rtl/${core}/run.sh" --sim-only
  echo "== negative controls: $core =="
  "${REPO_ROOT}/verification/rtl/${core}/run.sh" --negative-control
done

echo "== trng_if: stub and real-sibling benches, then negative controls =="
"${REPO_ROOT}/verification/rtl/trng_if/run.sh"
"${REPO_ROOT}/verification/rtl/trng_if/run.sh" --negative-control

echo "== formal: P-7, P-8, P-9 (reach_*/neg_* must fail) =="
"${REPO_ROOT}/verification/formal/run.sh"

echo "ci-verify: all flows met their expectation"
