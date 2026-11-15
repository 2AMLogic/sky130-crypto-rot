# flow/common/core_flow.sh -- shared driver steps for the per-core
# verification/rtl/<core>/run.sh scripts. Source it; do not execute it.
#
# The caller sets HERE (its own directory) and NAME (the core directory name,
# also flow/build/<NAME>), parses its options with core_flow_parse_opts below
# (the common flags plus whatever the core declares), then calls the steps.
# Synthesis is a single corner (tt_025C_1v80), pre-P&R, cell area only.
#
# Every core ends on core_flow_finish, which owns the --sim-only split: CI asks
# each core for its own simulations and nothing else (scripts/ci-verify.sh), so
# neither synthesis nor the record verdict may run on that path.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${REPO_ROOT}/flow/build/${NAME}"
PDK_ROOT="${PDK_ROOT:-${HOME}/.ciel}"

# The negative-control evidence for the benches whose assertion messages carry
# no distinctive prefix (drbg, trng_if -- see core_flow_negctl_one): the bench's
# own "SUMMARY ... failures=<n>" line with a non-zero n, matched in the cocotb
# log. One definition here instead of a copy per core; the same log is what
# core_flow_summaries reads.
BENCH_LOG=.klt/functional-verification/test_icarus.log
NEG_EVIDENCE='SUMMARY.*failures=[1-9][0-9]*'

# core_flow_parse_opts "$@" -- the one option parser, instead of a copy per
# core. Recognizes the common three flags (--record, --negative-control,
# --sim-only -> RECORD, NEG, SIM_ONLY) and calls core_flow_check_opts itself,
# so a core cannot forget that pair check (trng_if once did). A core keeps only
# what is genuinely its own, declared before the call:
#   CORE_FLOW_EXTRA_OPTS    "<flag>:<VAR>" pairs; passing <flag> sets <VAR> to
#                           1 (sha256: --million-a:MILLION; trng_if:
#                           --skip-real:SKIP_REAL). The core initializes the
#                           variable itself and may read it with the opposite
#                           sense (SKIP_REAL defaults 0).
#   CORE_FLOW_UNSUPPORTED   a flag the driver knows but this core does not
#                           (trng_if: --sim-only, which stops before a
#                           synthesis this core never runs). Passing one is
#                           rejected by name, before the case below can claim
#                           it as a common flag.
# Unknown options keep the original message and exit status.
core_flow_parse_opts() {
  RECORD=0; NEG=0; SIM_ONLY=0
  local arg pair
  for arg in "$@"; do
    case " ${CORE_FLOW_UNSUPPORTED:-} " in
      *" ${arg} "*)
        echo "unsupported option: ${arg}" >&2
        exit 2 ;;
    esac
    case "${arg}" in
      --record) RECORD=1 ;;
      --negative-control) NEG=1 ;;
      --sim-only) SIM_ONLY=1 ;;
      *)
        for pair in ${CORE_FLOW_EXTRA_OPTS:-}; do
          if [ "${arg}" = "${pair%%:*}" ]; then
            printf -v "${pair#*:}" '1'
            continue 2
          fi
        done
        echo "unknown option: ${arg}" >&2
        exit 2 ;;
    esac
  done
  core_flow_check_opts "${SIM_ONLY}" "${RECORD}"
}

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

# core_flow_negctl_request <base request> <define> -- the base request document
# with <define> added to options.defines (value null, as `-D<define>` would),
# on stdout. An empty <define> yields the base document unchanged.
#
# This is what makes a negative control a control. A control is only evidence
# if it runs the SAME bench on the SAME sources as the positive run with
# exactly one fault injected, and until issue #161 that held only by hand: each
# control had its own tracked copy of the positive request, so a source added
# to sim-request.json and not to its copies left a control that failed for an
# unrelated reason (a missing module) and was still counted as "caught".
# Deriving the control from the positive request makes "same bench, one fault"
# true by construction. verification/rtl/trng_if/mk_req.py reached the same
# conclusion from the other direction (issue #136).
core_flow_negctl_request() {
  python3 -I -c 'import json, sys
doc = json.load(open(sys.argv[1]))
if sys.argv[2]:
    doc.setdefault("options", {}).setdefault("defines", {})[sys.argv[2]] = None
json.dump(doc, sys.stdout, indent=2)' "${1}" "${2}"
}

# core_flow_negctl_one <base request> <define> <json name> <result label> \
#                      <grep pattern> <what the bench wrongly passed> \
#                      [evidence file]
#
# Derives <base request> + <define> (above) and feeds it to `klt` on stdin, so
# the corrupted request is never a file in the tree. Relative `sources` paths
# in a stdin request resolve against the working directory and `klt` writes its
# artifacts there too -- verified against the pinned klayout-tools 0.8.0 -- and
# core_flow_setup has already `cd`-ed to the bench's own directory, which is
# what the tracked request files resolved against. A caller that runs these
# steps from anywhere else must pass <base request> and <evidence file> to
# match. The derived document is also written to ${OUT} so a failing run can be
# read back; nothing reads it, and it is build scratch, not tracked evidence.
#
# An empty <define> runs <base request> unchanged: verification/rtl/trng_if
# generates its requests with the fault already in them (mk_req.py), so it
# needs the evidence discipline below without the derivation.
#
# Demands TWO things of the run: `klt` must exit
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
  local evidence="${7:-.klt/functional-verification/results_icarus.xml}"
  local request caught
  # Not `local request=$(...)`: that would discard the generator's exit status.
  if ! request="$(core_flow_negctl_request "${1}" "${2}")"; then
    echo "FAIL: could not derive ${1}${2:+ + ${2}} -- the control never ran" >&2
    exit 1
  fi
  printf '%s\n' "${request}" > "${OUT}/${3%.json}-request.json"
  rm -f "${evidence}"
  if printf '%s\n' "${request}" \
      | klt functional-verification - --format json > "${OUT}/${3}"; then
    echo "FAIL: the bench passed with ${6}" >&2
    exit 1
  fi
  caught="$(grep -o "${5}" "${evidence}" 2>/dev/null | head -1 || true)"
  if [ -z "${caught}" ]; then
    echo "FAIL: ${6}: klt exited non-zero but ${evidence} reports no caught" \
         "failure -- the build, not the bench, may have failed" >&2
    exit 1
  fi
  _json_line "${OUT}/${3}" '"'"${4}"'", d["status"], "(expected fail)"'
  echo "${caught}"
}

# core_flow_negctl <define> <what it corrupts> <noun> -- exit 0 only if the
# bench catches it. The one-control shape: sim-request.json plus <define>.
core_flow_negctl() {
  echo "== negative control: ${1} ${2}; the bench must fail =="
  core_flow_negctl_one sim-request.json "${1}" negctl.json "negative control:" \
    'first failing vector: [^&]*' "a corrupted ${3}"
  exit 0
}

# core_flow_status <sim json> -- the one-line "<status> <passed>/<total> tests"
# print after each simulation; drbg open-coded it per elaboration and trng_if
# wrapped it as status().
core_flow_status() {
  _json_line "$1" 'd["status"], d["passed_count"], "/", d["test_count"], "tests"'
}

# core_flow_summaries [--first] -- every "SUMMARY ..." line in the cocotb log
# (${BENCH_LOG}, above); --first keeps only the first, for a run that produces
# one elaboration per log.
core_flow_summaries() {
  if [ "${1:-}" = "--first" ]; then
    grep -o 'SUMMARY[^<]*' "${BENCH_LOG}" | head -1 || true
  else
    grep -o 'SUMMARY[^<]*' "${BENCH_LOG}" || true
  fi
}

core_flow_sim() {
  echo "== RTL simulation (klt functional-verification: cocotb + Icarus) =="
  klt functional-verification sim-request.json --format json > "${OUT}/sim.json"
  core_flow_status "${OUT}/sim.json"
  core_flow_summaries --first
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
