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
#                                                       # (exit 0 only if the bench catches all)
#
# Two elaborations (see test_drbg.py): the shipped 16/8-word seed widths scored
# against verification/model/ctr_drbg.py, and 6/4 words replaying the AES-128
# use-df CAVP records whose personalization/additional-input lengths are 0.
# Exit 0 only if both simulations passed and the synthesis is ok with no latches.
# Synthesis is a single corner (tt_025C_1v80), pre-P&R, cell area only; no STA,
# no timing claim.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../../.." && pwd)"
OUT="${REPO_ROOT}/flow/build/drbg"
PDK_ROOT="${PDK_ROOT:-${HOME}/.ciel}"

RECORD=0; NEG=0
for arg in "$@"; do
  case "${arg}" in
    --record) RECORD=1 ;;
    --negative-control) NEG=1 ;;
    *) echo "unknown option: ${arg}" >&2; exit 2 ;;
  esac
done

if [ ! -x "${REPO_ROOT}/.venv/bin/klt" ]; then
  echo "error: ${REPO_ROOT}/.venv is not provisioned." >&2
  echo "  -> run ./scripts/setup-env.sh first." >&2
  exit 1
fi
export PATH="${REPO_ROOT}/.venv/bin:${PATH}"

mkdir -p "${OUT}"
cd "${HERE}"

sim() { # sim <request> <mode> <out json>; returns klt's exit status
  DRBG_BENCH_MODE="$2" klt functional-verification "$1" --format json > "$3"
}
summary_line() { grep -o 'SUMMARY[^<]*' .klt/functional-verification/test_icarus.log | head -1 || true; }

if [ "${NEG}" = 1 ]; then
  echo "== negative controls: each corrupted build MUST fail =="
  bad=0
  for spec in "sim-negctl-df-request.json:shipped:K0 bit flipped in the df" \
              "sim-negctl-upd-request.json:shipped:one bit of V flipped in Update" \
              "sim-negctl-interval-request.json:shipped:one request too many before RESEED_REQUIRED" \
              "sim-negctl-cavp-request.json:cavp:CAVP replay with Update corrupted"; do
    IFS=: read -r req mode label <<< "${spec}"
    if sim "${req}" "${mode}" "${OUT}/negctl.json"; then
      echo "FAIL: the bench passed with a corrupted build (${label})" >&2; bad=1
    else
      echo "negative control (${label}): bench failed as required"
      summary_line | cut -c1-200
    fi
  done
  exit "${bad}"
fi

echo "== RTL simulation, shipped 16/8-word elaboration (klt functional-verification: cocotb + Icarus) =="
sim sim-request.json shipped "${OUT}/sim.json"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["status"], d["passed_count"], "/", d["test_count"], "tests")' "${OUT}/sim.json"
summary_line | tee "${OUT}/summary-shipped.txt"

echo "== RTL simulation, 6/4-word elaboration: CAVP AES-128 use-df replay =="
sim sim-cavp-request.json cavp "${OUT}/cavp.json"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["status"], d["passed_count"], "/", d["test_count"], "tests")' "${OUT}/cavp.json"
summary_line | tee "${OUT}/summary-cavp.txt"

echo "== synthesis of drbg_top (klt synthesize -> sky130_fd_sc_hd, tt_025C_1v80) =="
klt synthesize synth-request.json --pdk sky130A --pdk-root "${PDK_ROOT}" \
  --format json > "${OUT}/synth.json"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["status"], d["instance_count"], "instances", d["area_um2"], "um2")' "${OUT}/synth.json"

if [ "${RECORD}" = 1 ]; then
  python3 "${HERE}/make_record.py" --out-dir "${OUT}" --pdk-root "${PDK_ROOT}"
else
  python3 "${HERE}/make_record.py" --out-dir "${OUT}" --pdk-root "${PDK_ROOT}" --check-only
fi
