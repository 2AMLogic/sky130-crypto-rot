#!/usr/bin/env bash
#
# verification/rtl/sha256/run.sh -- simulate and synthesize rtl/sha256/sha256_core.v
# in the pinned environment.
#
#   ./scripts/setup-env.sh                              # once: .venv, pinned yosys, PDK
#   ./verification/rtl/sha256/run.sh                    # cocotb + Icarus, then klt synthesize
#   ./verification/rtl/sha256/run.sh --record           # same, then write a record under
#                                                       # verification/records/sha256-core-sim-synth/records/
#   ./verification/rtl/sha256/run.sh --million-a        # also run the FIPS 180-4 million-`a` KAT
#                                                       # (about 2M cycles, ~10 min in Icarus)
#   ./verification/rtl/sha256/run.sh --sim-only         # the positive simulations only: stop before
#                                                       # synthesis (what scripts/ci-verify.sh runs)
#   ./verification/rtl/sha256/run.sh --negative-control # K[17] flipped by one bit: MUST fail
#                                                       # (exit 0 only if the bench catches it); also
#                                                       # omits hh from the scrub list: test_scrub MUST fail
#   ./verification/rtl/sha256/run.sh --gate-level       # also run the SAME bench (test_scrub and
#                                                       # test_sha256_core) against the klt synthesize
#                                                       # netlist of this run (sky130_fd_sc_hd cells;
#                                                       # the two gate-level runs measured ~9 s and
#                                                       # ~27 min -- slow, hence not on CI's path)
#   ./verification/rtl/sha256/run.sh --gate-level --record
#                                                       # same, and the record then carries the
#                                                       # netlist hash, cell models and delay model
#   ./verification/rtl/sha256/run.sh --gate-level --negative-control
#                                                       # synthesize the K-corrupted build and run the
#                                                       # bench on THAT netlist: MUST fail
#
# Exit 0 only if the simulation passed and the synthesis is ok with no latches.
# Without --million-a that KAT is NOT run and a record says so. Synthesis is a
# single corner (tt_025C_1v80), pre-P&R, cell area only; no STA, no timing claim.
#
# --gate-level is pre-layout and carries no SDF, so it is a functional check of
# the mapped gates, not a timing one; the SDF-annotated post-route run is issue
# #82. The million-`a` KAT is NOT run at gate level even with --million-a -- it
# is ~2M cycles against behavioural cell models -- and the record says so. The
# mode is deliberately NOT on CI's path (scripts/ci-verify.sh).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME=sha256
source "${HERE}/../../../flow/common/core_flow.sh"

RECORD=0; MILLION=0; NEG=0; SIM_ONLY=0; GATE_LEVEL=0
for arg in "$@"; do
  case "${arg}" in
    --record) RECORD=1 ;;
    --million-a) MILLION=1 ;;
    --negative-control) NEG=1 ;;
    --sim-only) SIM_ONLY=1 ;;
    --gate-level) GATE_LEVEL=1 ;;
    *) echo "unknown option: ${arg}" >&2; exit 2 ;;
  esac
done
core_flow_check_opts "${SIM_ONLY}" "${RECORD}" "${GATE_LEVEL}"

# The committed vector set runs at gate level, plus test_scrub -- which is the
# testcase that reads all thirteen scrubbed registers hierarchically, so running
# it is what shows those names survive synthesis as readable netlist wires. Not
# test_million_a: ~2M cycles against behavioural cell models is impractical, and
# the record names it as not run at gate level, with that reason.
GATE_TESTCASES="test_scrub test_sha256_core"
GATE_EXCLUDED="test_million_a=about 2M cycles against behavioural cell models, hours rather than minutes; the RTL run still covers it under --million-a"

core_flow_setup
if [ "${NEG}" = 1 ] && [ "${GATE_LEVEL}" = 1 ]; then
  core_flow_gate_negctl SHA256_NEG_CTRL test_sha256_core \
    "SHA256_NEG_CTRL flips one K constant" "constant"
fi
if [ "${NEG}" = 1 ]; then
  echo "== negative control: SHA256_NEG_SCRUB omits hh from the scrub list; test_scrub must fail =="
  core_flow_negctl_one sim-scrub-negctl-request.json scrub-negctl.json \
    "scrub negative control:" 'first failing scrub check: [^&]*' \
    "hh left out of the scrub"
  core_flow_negctl "SHA256_NEG_CTRL flips one K constant" "constant"
fi

# scrub runs first: make_record.py reads the SUMMARY line from the last klt log
echo "== scrub (zeroize) test =="
klt functional-verification sim-scrub-request.json --format json > "${OUT}/scrub.json"
_json_line "${OUT}/scrub.json" '"scrub:", d["status"], d["passed_count"], "/", d["test_count"], "tests"'
core_flow_sim
rm -f "${OUT}/million.json"
if [ "${MILLION}" = 1 ]; then
  echo "== million-a KAT =="
  klt functional-verification sim-million-a-request.json --format json > "${OUT}/million.json"
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("million-a:", d["status"])' "${OUT}/million.json"
fi
core_flow_finish "${SIM_ONLY}" "${RECORD}"
