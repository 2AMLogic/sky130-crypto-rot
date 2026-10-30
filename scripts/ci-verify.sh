#!/usr/bin/env bash
#
# scripts/ci-verify.sh -- the cheapest subset of the local verification flows
# that still trips every negative control (issue #85). CI runs exactly this.
#
#   ./scripts/setup-env.sh                  # once: .venv, pinned yosys, PDK
#   ./scripts/ci-verify.sh
#
# Per core: the positive simulation(s), then every negative control, which
# must FAIL (the run.sh exits non-zero if one passes). Then the SymbiYosys
# tasks, whose reach_*/neg_* tasks must fail. Nothing is recorded.
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

sim() { # sim <dir under verification/rtl> <request> [DRBG_BENCH_MODE]
  echo "== sim: $1/$2 =="
  (cd "${REPO_ROOT}/verification/rtl/$1" && DRBG_BENCH_MODE="${3:-}" \
    klt functional-verification "$2" --format json > /dev/null)
}

sim sha256 sim-request.json
sim sha256 sim-scrub-request.json
sim aes sim-request.json
sim drbg sim-request.json shipped
sim drbg sim-cavp-request.json cavp

for core in sha256 aes drbg; do
  echo "== negative controls: $core =="
  "${REPO_ROOT}/verification/rtl/${core}/run.sh" --negative-control
done

echo "== trng_if: stub and real-sibling benches, then negative controls =="
"${REPO_ROOT}/verification/rtl/trng_if/run.sh"
"${REPO_ROOT}/verification/rtl/trng_if/run.sh" --negative-control

echo "== formal: P-7, P-8, P-9 (reach_*/neg_* must fail) =="
"${REPO_ROOT}/verification/formal/run.sh"

echo "ci-verify: all flows met their expectation"
