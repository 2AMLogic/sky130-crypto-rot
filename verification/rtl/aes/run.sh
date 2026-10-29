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
REPO_ROOT="$(cd "${HERE}/../../.." && pwd)"
OUT="${REPO_ROOT}/flow/build/aes"
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
# The venv's bin/ must lead $PATH so klt runs the pinned yosys, not a host one.
export PATH="${REPO_ROOT}/.venv/bin:${PATH}"

mkdir -p "${OUT}"
cd "${HERE}"

if [ "${NEG}" = 1 ]; then
  echo "== negative control: AES_NEG_CTRL flips one S-box output bit; the bench must fail =="
  if klt functional-verification sim-negctl-request.json --format json > "${OUT}/negctl.json"; then
    echo "FAIL: the bench passed with a corrupted S-box" >&2
    exit 1
  fi
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("negative control:", d["status"], "(expected fail)")' "${OUT}/negctl.json"
  grep -o 'first failing vector: [^&]*' .klt/functional-verification/results_icarus.xml | head -1
  exit 0
fi

echo "== RTL simulation (klt functional-verification: cocotb + Icarus) =="
klt functional-verification sim-request.json --format json > "${OUT}/sim.json"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["status"], d["passed_count"], "/", d["test_count"], "tests")' "${OUT}/sim.json"
grep -o 'SUMMARY[^<]*' .klt/functional-verification/test_icarus.log | head -1 || true

echo "== synthesis (klt synthesize -> sky130_fd_sc_hd, tt_025C_1v80) =="
klt synthesize synth-request.json --pdk sky130A --pdk-root "${PDK_ROOT}" \
  --format json > "${OUT}/synth.json"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["status"], d["instance_count"], "instances", d["area_um2"], "um2")' "${OUT}/synth.json"

if [ "${RECORD}" = 1 ]; then
  python3 "${HERE}/make_record.py" --out-dir "${OUT}" --pdk-root "${PDK_ROOT}"
else
  python3 "${HERE}/make_record.py" --out-dir "${OUT}" --pdk-root "${PDK_ROOT}" --check-only
fi
