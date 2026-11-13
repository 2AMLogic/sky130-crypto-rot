#!/usr/bin/env bash
#
# verification/rtl/drbg/run.sh -- simulate and synthesize rtl/drbg/ctr_drbg.v
# (with its AES engine, in tb_drbg.v) and map rtl/drbg/drbg_top.v, in the
# pinned environment.
#
#   ./scripts/setup-env.sh                              # once: .venv, pinned yosys, PDK
#   ./verification/rtl/drbg/run.sh                      # shipped-width cross-check, CAVP replay, synthesis
#   ./verification/rtl/drbg/run.sh --record             # same, then write a record under
#                                                       # verification/records/drbg-sim-synth/records/
#   ./verification/rtl/drbg/run.sh --negative-control   # four corrupted builds (df key, Update V,
#                                                       # reseed interval, and the CAVP replay on
#                                                       # a corrupted Update): every one MUST fail
#                                                       # (exit 0 only if the bench catches all;
#                                                       # the run stops at the first it does not)
#
# Two elaborations (see test_drbg.py): the shipped 16/8-word seed widths scored
# against verification/model/ctr_drbg.py, and 6/4 words replaying the AES-128
# use-df CAVP records whose personalization/additional-input lengths are 0.
# Exit 0 only if both simulations passed and the synthesis is ok with no latches.
# Synthesis is a single corner (tt_025C_1v80), pre-P&R, cell area only; no STA,
# no timing claim.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME=drbg
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

BENCH_LOG=.klt/functional-verification/test_icarus.log
# This bench asserts with an unprefixed message, so what shows that the BENCH
# (not the build) failed is its own SUMMARY line with a non-zero failure count.
NEG_EVIDENCE='SUMMARY.*failures=[1-9][0-9]*'

sim() { # sim <request> <mode> <out json>; returns klt's exit status
  DRBG_BENCH_MODE="$2" klt functional-verification "$1" --format json > "$3"
}
summary_line() { grep -o 'SUMMARY[^<]*' "${BENCH_LOG}" | head -1 || true; }

if [ "${NEG}" = 1 ]; then
  echo "== negative controls: each corrupted build MUST fail =="
  DRBG_BENCH_MODE=shipped core_flow_negctl_one \
    sim-negctl-df-request.json negctl-df.json \
    "negative control (K0 bit flipped in the df):" "${NEG_EVIDENCE}" \
    "K0 bit flipped in the df" "${BENCH_LOG}"
  DRBG_BENCH_MODE=shipped core_flow_negctl_one \
    sim-negctl-upd-request.json negctl-upd.json \
    "negative control (one bit of V flipped in Update):" "${NEG_EVIDENCE}" \
    "one bit of V flipped in Update" "${BENCH_LOG}"
  DRBG_BENCH_MODE=shipped core_flow_negctl_one \
    sim-negctl-interval-request.json negctl-interval.json \
    "negative control (one request too many before RESEED_REQUIRED):" "${NEG_EVIDENCE}" \
    "one request too many before RESEED_REQUIRED" "${BENCH_LOG}"
  DRBG_BENCH_MODE=cavp core_flow_negctl_one \
    sim-negctl-cavp-request.json negctl-cavp.json \
    "negative control (CAVP replay with Update corrupted):" "${NEG_EVIDENCE}" \
    "the CAVP replay with Update corrupted" "${BENCH_LOG}"
  exit 0
fi

echo "== RTL simulation, shipped 16/8-word elaboration (klt functional-verification: cocotb + Icarus) =="
sim sim-request.json shipped "${OUT}/sim.json"
_json_line "${OUT}/sim.json" 'd["status"], d["passed_count"], "/", d["test_count"], "tests"'
summary_line | tee "${OUT}/summary-shipped.txt"

echo "== RTL simulation, 6/4-word elaboration: CAVP AES-128 use-df replay =="
sim sim-cavp-request.json cavp "${OUT}/cavp.json"
_json_line "${OUT}/cavp.json" 'd["status"], d["passed_count"], "/", d["test_count"], "tests"'
summary_line | tee "${OUT}/summary-cavp.txt"

core_flow_synth drbg_top
core_flow_verdict "${RECORD}"
