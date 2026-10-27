# flow/common/core_flow.sh -- shared driver steps for the per-core
# verification/rtl/<core>/run.sh scripts. Source it; do not execute it.
#
# The caller sets HERE (its own directory) and NAME (the core directory name,
# also flow/build/<NAME>), parses its own options, then calls the steps below.
# Synthesis is a single corner (tt_025C_1v80), pre-P&R, cell area only.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${REPO_ROOT}/flow/build/${NAME}"
PDK_ROOT="${PDK_ROOT:-${HOME}/.ciel}"

_json_line() {  # _json_line <file> <python print expression over d>
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print('"$2"')' "$1"
}

core_flow_setup() {
  if [ ! -x "${REPO_ROOT}/.venv/bin/klt" ]; then
    echo "error: ${REPO_ROOT}/.venv is not provisioned." >&2
    echo "  -> run ./scripts/setup-env.sh first." >&2
    exit 1
  fi
  # The venv's bin/ must lead $PATH so klt runs the pinned yosys, not a host one.
  export PATH="${REPO_ROOT}/.venv/bin:${PATH}"
  mkdir -p "${OUT}"
  cd "${HERE}"
}

# core_flow_negctl <what is corrupted> -- exit 0 only if the bench catches it.
core_flow_negctl() {
  echo "== negative control: ${1}; the bench must fail =="
  if klt functional-verification sim-negctl-request.json --format json > "${OUT}/negctl.json"; then
    echo "FAIL: the bench passed with a corrupted ${2}" >&2
    exit 1
  fi
  _json_line "${OUT}/negctl.json" '"negative control:", d["status"], "(expected fail)"'
  grep -o 'first failing vector: [^&]*' .klt/functional-verification/results_icarus.xml | head -1
  exit 0
}

core_flow_sim() {
  echo "== RTL simulation (klt functional-verification: cocotb + Icarus) =="
  klt functional-verification sim-request.json --format json > "${OUT}/sim.json"
  _json_line "${OUT}/sim.json" 'd["status"], d["passed_count"], "/", d["test_count"], "tests"'
  grep -o 'SUMMARY[^<]*' .klt/functional-verification/test_icarus.log | head -1 || true
}

core_flow_synth() {
  echo "== synthesis (klt synthesize -> sky130_fd_sc_hd, tt_025C_1v80) =="
  klt synthesize synth-request.json --pdk sky130A --pdk-root "${PDK_ROOT}" \
    --format json > "${OUT}/synth.json"
  _json_line "${OUT}/synth.json" 'd["status"], d["instance_count"], "instances", d["area_um2"], "um2"'
}

# core_flow_verdict <RECORD 0|1> -- verdict, plus a record when RECORD=1.
core_flow_verdict() {
  if [ "${1}" = 1 ]; then
    python3 "${HERE}/make_record.py" --out-dir "${OUT}" --pdk-root "${PDK_ROOT}"
  else
    python3 "${HERE}/make_record.py" --out-dir "${OUT}" --pdk-root "${PDK_ROOT}" --check-only
  fi
}
