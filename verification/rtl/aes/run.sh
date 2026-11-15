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
#   ./verification/rtl/aes/run.sh --timing             # pre-layout setup timing, no simulation:
#                                                       # synthesize at ss_100C_1v60 with a 20 ns
#                                                       # clock target, then klt sta on the netlist
#   ./verification/rtl/aes/run.sh --timing --record    # same, then write the shared pre-layout STA
#                                                       # record (verification/records/core-pre-layout-sta/;
#                                                       # sha256 must have run --timing already)
#   ./verification/rtl/aes/run.sh --negative-control    # one S-box output bit flipped: MUST fail
#                                                       # (exit 0 only if the bench catches it)
#
# Exit 0 only if the simulation passed and the synthesis is ok with no latches.
# Synthesis is a single corner (tt_025C_1v80), pre-P&R, cell area only; no STA,
# no timing claim. --timing is the one mode that measures timing: a single
# corner (ss_100C_1v60), pre-layout, worst setup slack reported as data -- a
# negative slack does not fail the run, and the mode needs `openroad` on
# $PATH (klt sta shells out to it). It never runs in CI: no PDK, no openroad.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME=aes
source "${HERE}/../../../flow/common/core_flow.sh"

TIMING=0; CORE_FLOW_EXTRA_OPTS="--timing:TIMING"
core_flow_parse_opts "$@"
if [ "${TIMING}" = 1 ]; then
  if [ "${SIM_ONLY}" = 1 ] || [ "${NEG}" = 1 ]; then
    echo "error: --timing runs neither the simulations nor a negative control;" >&2
    echo "  combine it with nothing (or with --record alone)." >&2
    exit 2
  fi
  core_flow_setup
  core_flow_sta "aes_core"
  if [ "${RECORD}" = 1 ]; then
    python3 "${REPO_ROOT}/flow/common/make_timing_record.py" --pdk-root "${PDK_ROOT}"
  fi
  exit 0
fi

core_flow_setup
[ "${NEG}" = 1 ] && core_flow_negctl AES_NEG_CTRL "flips one S-box output bit" "S-box"

core_flow_sim
core_flow_finish "${SIM_ONLY}" "${RECORD}"
