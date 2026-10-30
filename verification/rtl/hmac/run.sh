#!/usr/bin/env bash
#
# verification/rtl/hmac/run.sh -- simulate and synthesize rtl/hmac/hmac_sha256.v
# (with rtl/sha256/sha256_core.v) in the pinned environment.
#
#   ./scripts/setup-env.sh                              # once: .venv, pinned yosys, PDK
#   ./verification/rtl/hmac/run.sh                      # cocotb + Icarus, then klt synthesize
#   ./verification/rtl/hmac/run.sh --record             # same, then write a record under
#                                                       # verification/records/hmac-sha256-sim-synth/records/
#   ./verification/rtl/hmac/run.sh --negative-control   # one opad bit flipped: MUST fail
#                                                       # (exit 0 only if the bench catches it)
#                                                       # also: HMAC_NEG_SCRUB: clear reaches the core by neither reset nor scrub
#
# Exit 0 only if the simulation passed and the synthesis is ok with no latches.
# Synthesis is a single corner (tt_025C_1v80), pre-P&R, cell area only; no STA,
# no timing claim.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME=hmac
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
  echo "== negative control: HMAC_NEG_CTRL flips one opad bit; the bench must fail =="
  core_flow_negctl_one sim-negctl-request.json negctl.json "negative control:" \
    'first failing vector: [^&]*' "a corrupted opad constant"
  echo "== negative control: HMAC_NEG_SCRUB keeps clear away from the core; the bench must fail =="
  core_flow_negctl_one sim-scrub-negctl-request.json scrub-negctl.json "scrub negative control:" \
    'first failing [a-z ]*: [^&]*' "clear not reaching the core"
  exit 0
fi

core_flow_sim
core_flow_synth
core_flow_verdict "${RECORD}"
