#!/usr/bin/env bash
#
# verification/rtl/keyladder/run.sh -- simulate and synthesize rtl/keyladder/keyladder.v
# (with rtl/hmac/hmac_sha256.v and rtl/sha256/sha256_core.v) in the pinned environment.
#
#   ./scripts/setup-env.sh                              # once: .venv, pinned yosys, PDK
#   ./verification/rtl/keyladder/run.sh                      # cocotb + Icarus, then klt synthesize
#   ./verification/rtl/keyladder/run.sh --record             # same, then write a record under
#                                                       # verification/records/keyladder-sim-synth/records/
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

RECORD=0; NEG=0
for arg in "$@"; do
  case "${arg}" in
    --record) RECORD=1 ;;
    --negative-control) NEG=1 ;;
    *) echo "unknown option: ${arg}" >&2; exit 2 ;;
  esac
done

core_flow_setup

if [ "${NEG}" = 1 ]; then
  echo "== negative controls: each must make the bench fail =="
  for c in mask lock zeroize; do
    core_flow_negctl_one "sim-negctl-${c}-request.json" "negctl-${c}.json" "negative control ${c} :" \
      'first failing check: [^&]*' "negative control '${c}'"
  done
  exit 0
fi

core_flow_sim
core_flow_synth
core_flow_verdict "${RECORD}"
