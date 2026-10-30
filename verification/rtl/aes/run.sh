#!/usr/bin/env bash
#
# verification/rtl/aes/run.sh -- simulate and synthesize rtl/aes/aes_core.v
# in the pinned environment.
#
#   ./scripts/setup-env.sh                              # once: .venv, pinned yosys, PDK
#   ./verification/rtl/aes/run.sh                       # cocotb + Icarus, then klt synthesize
#   ./verification/rtl/aes/run.sh --record              # same, then write a record under
#                                                       # verification/records/aes-core-sim-synth/records/
#   ./verification/rtl/aes/run.sh --negative-control    # one S-box output bit flipped: MUST fail
#                                                       # (exit 0 only if the bench catches it)
#
# Exit 0 only if the simulation passed and the synthesis is ok with no latches.
# Synthesis is a single corner (tt_025C_1v80), pre-P&R, cell area only; no STA,
# no timing claim.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME=aes
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
[ "${NEG}" = 1 ] && core_flow_negctl "AES_NEG_CTRL flips one S-box output bit" "S-box"

core_flow_sim
core_flow_synth
core_flow_verdict "${RECORD}"
