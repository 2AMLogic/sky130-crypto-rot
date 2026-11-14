#!/usr/bin/env bash
#
# verification/rtl/aes/run.sh -- simulate and synthesize rtl/aes/aes_core.v
# in the pinned environment.
#
#   ./scripts/setup-env.sh                              # once: .venv, pinned yosys, PDK
#   ./verification/rtl/aes/run.sh                       # cocotb + Icarus, then klt synthesize
#   ./verification/rtl/aes/run.sh --record              # same, then write a record under
#                                                       # verification/records/aes-core-sim-synth/records/
#   ./verification/rtl/aes/run.sh --sim-only            # simulation only: stop before synthesis
#                                                       # (what scripts/ci-verify.sh runs)
#   ./verification/rtl/aes/run.sh --negative-control    # one S-box output bit flipped: MUST fail
#                                                       # (exit 0 only if the bench catches it)
#   ./verification/rtl/aes/run.sh --gate-level          # also run the SAME bench against the
#                                                       # klt synthesize netlist of this run
#                                                       # (sky130_fd_sc_hd cells; the gate-level
#                                                       # run itself measured ~82 s)
#   ./verification/rtl/aes/run.sh --gate-level --record # same, and the record then carries the
#                                                       # netlist hash, cell models and delay model
#   ./verification/rtl/aes/run.sh --gate-level --negative-control
#                                                       # synthesize the S-box-corrupted build and
#                                                       # run the bench on THAT netlist: MUST fail
#
# Exit 0 only if the simulation passed and the synthesis is ok with no latches.
# Synthesis is a single corner (tt_025C_1v80), pre-P&R, cell area only; no STA,
# no timing claim.
#
# --gate-level is pre-layout and carries no SDF, so it is a functional check of
# the mapped gates, not a timing one; the SDF-annotated post-route run is issue
# #82. It is deliberately NOT on CI's path (scripts/ci-verify.sh): it needs the
# PDK's cell models, and --sim-only (what CI runs) never synthesizes.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME=aes
source "${HERE}/../../../flow/common/core_flow.sh"

RECORD=0; NEG=0; SIM_ONLY=0; GATE_LEVEL=0
for arg in "$@"; do
  case "${arg}" in
    --record) RECORD=1 ;;
    --negative-control) NEG=1 ;;
    --sim-only) SIM_ONLY=1 ;;
    --gate-level) GATE_LEVEL=1 ;;
    *) echo "unknown option: ${arg}" >&2; exit 2 ;;
  esac
done
core_flow_check_opts "${SIM_ONLY}" "${RECORD}" "${GATE_LEVEL}"

# The whole committed vector set runs at gate level: every internal register the
# bench reads hierarchically (state_q, rk_q, rnd_q) survives synthesis as a
# readable netlist wire, so no check is dropped and none is listed in the record
# as not run at gate level.
GATE_TESTCASES="test_aes_core"

core_flow_setup
if [ "${NEG}" = 1 ] && [ "${GATE_LEVEL}" = 1 ]; then
  core_flow_gate_negctl AES_NEG_CTRL test_aes_core \
    "AES_NEG_CTRL flips one S-box output bit" "S-box"
fi
[ "${NEG}" = 1 ] && core_flow_negctl "AES_NEG_CTRL flips one S-box output bit" "S-box"

core_flow_sim
core_flow_finish "${SIM_ONLY}" "${RECORD}"
