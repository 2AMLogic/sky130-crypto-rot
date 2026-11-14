# flow/common/core_flow.sh -- shared driver steps for the per-core
# verification/rtl/<core>/run.sh scripts. Source it; do not execute it.
#
# The caller sets HERE (its own directory) and NAME (the core directory name,
# also flow/build/<NAME>), parses its own options, then calls the steps below.
# Synthesis is a single corner (tt_025C_1v80), pre-P&R, cell area only.
#
# Every core ends on core_flow_finish, which owns the --sim-only split: CI asks
# each core for its own simulations and nothing else (scripts/ci-verify.sh), so
# neither synthesis nor the record verdict may run on that path.

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

# core_flow_negctl_one <request> <json name> <result label> <grep pattern> \
#                      <what the bench wrongly passed> [evidence file]
#
# Runs one corrupted build and demands TWO things of it: `klt` must exit
# non-zero, AND <grep pattern> must match in <evidence file> -- the bench's own
# report of the failure it caught. A non-zero `klt` exit on its own is not
# evidence: a build that never elaborated (a missing source, a renamed define,
# a malformed request) exits non-zero too, and a negative control that "passes"
# for that reason has tested nothing (issue #151). The evidence file is removed
# before the run, so a stale report left behind by an earlier control -- `klt`
# does not clear this directory when a build fails -- cannot stand in for this
# control's own.
#
# <evidence file> defaults to the cocotb results XML, which carries the failing
# assertion text: the aes, sha256, hmac and keyladder benches give that text a
# distinctive prefix ("first failing vector: ...") and match on it. The drbg and
# trng_if benches assert with an unprefixed message, so they pass the cocotb log
# instead and match their own "SUMMARY ... failures=<n>" line with a non-zero n.
#
# Does not exit 0 itself: the caller may chain several controls. Chaining stops
# at the first control the bench fails to catch (exit 1) rather than running the
# rest -- one uncaught fault already fails the run, and stopping leaves that
# control as the last thing printed. Every caller chains on this helper.
core_flow_negctl_one() {
  local evidence="${6:-.klt/functional-verification/results_icarus.xml}"
  local caught
  rm -f "${evidence}"
  if klt functional-verification "${1}" --format json > "${OUT}/${2}"; then
    echo "FAIL: the bench passed with ${5}" >&2
    exit 1
  fi
  caught="$(grep -o "${4}" "${evidence}" 2>/dev/null | head -1 || true)"
  if [ -z "${caught}" ]; then
    echo "FAIL: ${5}: klt exited non-zero but ${evidence} reports no caught" \
         "failure -- the build, not the bench, may have failed" >&2
    exit 1
  fi
  _json_line "${OUT}/${2}" '"'"${3}"'", d["status"], "(expected fail)"'
  echo "${caught}"
}

# core_flow_negctl <what is corrupted> <noun> -- exit 0 only if the bench catches it.
core_flow_negctl() {
  echo "== negative control: ${1}; the bench must fail =="
  core_flow_negctl_one sim-negctl-request.json negctl.json "negative control:" \
    'first failing vector: [^&]*' "a corrupted ${2}"
  exit 0
}

core_flow_sim() {
  echo "== RTL simulation (klt functional-verification: cocotb + Icarus) =="
  klt functional-verification sim-request.json --format json > "${OUT}/sim.json"
  _json_line "${OUT}/sim.json" 'd["status"], d["passed_count"], "/", d["test_count"], "tests"'
  grep -o 'SUMMARY[^<]*' .klt/functional-verification/test_icarus.log | head -1 || true
}

# core_flow_check_opts <SIM_ONLY 0|1> <RECORD 0|1> -- reject the one option pair
# that cannot mean anything, before a bench runs rather than after: a record is
# a simulation AND synthesis result, and --sim-only never synthesizes.
core_flow_check_opts() {
  if [ "${1}" = 1 ] && [ "${2}" = 1 ]; then
    echo "error: --sim-only and --record are mutually exclusive:" >&2
    echo "  --sim-only stops before synthesis, and a record reports one." >&2
    exit 2
  fi
}

# core_flow_synth [what] -- the optional name goes in the banner ("synthesis of <what>").
core_flow_synth() {
  echo "== synthesis${1:+ of ${1}} (klt synthesize -> sky130_fd_sc_hd, tt_025C_1v80) =="
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

# core_flow_finish <SIM_ONLY 0|1> <RECORD 0|1> [what] -- the tail every core
# shares. SIM_ONLY=1 stops here: that is the whole of CI's positive run, which
# has no PDK and mints no evidence. Otherwise synthesize, then settle the
# verdict (and write a record when RECORD=1).
core_flow_finish() {
  if [ "${1}" = 1 ]; then
    echo "== --sim-only: stopping before synthesis; no verdict, no record =="
    return 0
  fi
  core_flow_synth "${3:-}"
  core_flow_verdict "${2}"
}
