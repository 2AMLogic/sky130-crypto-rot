#!/usr/bin/env bash
#
# verification/rtl/crypto_rot_top/run.sh -- simulate and synthesize
# rtl/crypto_rot_top.v (with the aes, hmac/sha256, keyladder and
# drbg/trng_if blocks under it) in the pinned environment.
#
#   ./scripts/setup-env.sh                              # once: .venv, pinned yosys, PDK
#   ./verification/rtl/crypto_rot_top/run.sh            # cocotb + Icarus, then klt synthesize
#   ./verification/rtl/crypto_rot_top/run.sh --record   # same, then write a record under
#                                                       # verification/records/crypto-rot-top-sim/records/
#   ./verification/rtl/crypto_rot_top/run.sh --sim-only # simulation only: stop before synthesis
#                                                       # (what scripts/ci-verify.sh runs)
#   ./verification/rtl/crypto_rot_top/run.sh --negative-control
#                                                       # four controls (top zeroize disconnected,
#                                                       # class-1 fault unrecorded, ladder slot omitted
#                                                       # from zeroize, event swallowed by a same-cycle
#                                                       # register write): each MUST fail
#
# Exit 0 only if the simulation passed and the synthesis is ok with no latches.
# Synthesis is a single corner (tt_025C_1v80), pre-P&R, cell area only; no STA,
# no timing claim.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME=crypto_rot_top
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
  for pair in "topzero:TOP_NEG_ZEROIZE" "topfault:TOP_NEG_FAULT" "klzero:KL_NEG_ZEROIZE" "topirqsticky:TOP_NEG_IRQ_STICKY"; do
    c="${pair%%:*}"
    core_flow_negctl_one sim-request.json "${pair#*:}" "negctl-${c}.json" "negative control ${c} :" \
      'first failing check: [^&]*' "negative control '${c}'"
  done
  exit 0
fi

core_flow_sim
core_flow_finish "${SIM_ONLY}" "${RECORD}"
