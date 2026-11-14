#!/usr/bin/env bash
#
# verification/rtl/keyladder/run.sh -- simulate and synthesize rtl/keyladder/keyladder.v
# (with rtl/hmac/hmac_sha256.v and rtl/sha256/sha256_core.v) in the pinned environment.
#
#   ./scripts/setup-env.sh                              # once: .venv, pinned yosys, PDK
#   ./verification/rtl/keyladder/run.sh                      # cocotb + Icarus, then klt synthesize
#   ./verification/rtl/keyladder/run.sh --record             # same, then write a record under
#                                                       # verification/records/keyladder-sim-synth/records/
#   ./verification/rtl/keyladder/run.sh --sim-only           # simulation only: stop before synthesis
#                                                       # (what scripts/ci-verify.sh runs)
#   ./verification/rtl/keyladder/run.sh --negative-control   # three controls (mask check, lock check,
#                                                       # one slot omitted from zeroize): each MUST fail
#                                                       # (exit 0 only if the bench catches all three)
#
# Exit 0 only if the simulation passed and the synthesis is ok with no latches.
# Synthesis is a single corner (tt_025C_1v80), pre-P&R, cell area only; no STA,
# no timing claim.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME=keyladder
source "${HERE}/../../../flow/common/core_flow.sh"

RECORD=0; NEG=0; SIM_ONLY=0
for arg in "$@"; do
  case "${arg}" in
    --record) RECORD=1 ;;
    --negative-control) NEG=1 ;;
    --sim-only) SIM_ONLY=1 ;;
    *) echo "unknown option: ${arg}" >&2; exit 2 ;;
  esac
done
core_flow_check_opts "${SIM_ONLY}" "${RECORD}"

core_flow_setup

if [ "${NEG}" = 1 ]; then
  echo "== negative controls: each must make the bench fail =="
  # <control>:<define> pairs, not "KL_NEG_${c^^}": bash 3.2 (macOS) has no ^^.
  for pair in "mask:KL_NEG_MASK" "lock:KL_NEG_LOCK" "zeroize:KL_NEG_ZEROIZE"; do
    c="${pair%%:*}"
    core_flow_negctl_one sim-request.json "${pair#*:}" "negctl-${c}.json" "negative control ${c} :" \
      'first failing check: [^&]*' "negative control '${c}'"
  done
  exit 0
fi

core_flow_sim
core_flow_finish "${SIM_ONLY}" "${RECORD}"
