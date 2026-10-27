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
REPO_ROOT="$(cd "${HERE}/../../.." && pwd)"
OUT="${REPO_ROOT}/flow/build/keyladder"
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
  echo "== negative controls: each must make the bench fail =="
  for c in mask lock zeroize; do
    if klt functional-verification "sim-negctl-${c}-request.json" --format json > "${OUT}/negctl-${c}.json"; then
      echo "FAIL: the bench passed with negative control '${c}'" >&2
      exit 1
    fi
    python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("negative control", sys.argv[2], ":", d["status"], "(expected fail)")' "${OUT}/negctl-${c}.json" "${c}"
    grep -o 'first failing check: [^&]*' .klt/functional-verification/results_icarus.xml | head -1
  done
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
