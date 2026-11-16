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
#   ./verification/rtl/sha256/run.sh --timing          # pre-layout setup timing, no simulation:
#                                                       # synthesize at ss_100C_1v60 with a 20 ns
#                                                       # clock target, then klt sta on the netlist
#   ./verification/rtl/sha256/run.sh --timing --record # same, then write the shared pre-layout STA
#                                                       # record (verification/records/core-pre-layout-sta/;
#                                                       # aes must have run --timing already)
#   ./verification/rtl/sha256/run.sh --negative-control # K[17] flipped by one bit: MUST fail
#                                                       # (exit 0 only if the bench catches it); also
#                                                       # omits hh from the scrub list: test_scrub MUST fail
#
# Exit 0 only if the simulation passed and the synthesis is ok with no latches.
# Without --million-a that KAT is NOT run and a record says so. Synthesis is a
# single corner (tt_025C_1v80), pre-P&R, cell area only; no STA, no timing claim.
# --timing is the one mode that measures timing: a single corner
# (ss_100C_1v60), pre-layout, worst setup slack reported as data -- a negative
# slack does not fail the run, and the mode needs `openroad` on $PATH (klt sta
# shells out to it). It never runs in CI: no PDK, no openroad.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME=sha256
source "${HERE}/../../../flow/common/core_flow.sh"

MILLION=0; TIMING=0; CORE_FLOW_EXTRA_OPTS="--million-a:MILLION --timing:TIMING"
core_flow_parse_opts "$@"
if [ "${TIMING}" = 1 ]; then
  if [ "${SIM_ONLY}" = 1 ] || [ "${NEG}" = 1 ] || [ "${MILLION}" = 1 ]; then
    echo "error: --timing runs neither the simulations nor the million-a KAT;" >&2
    echo "  combine it with nothing (or with --record alone)." >&2
    exit 2
  fi
  core_flow_setup
  core_flow_sta "sha256_core"
  if [ "${RECORD}" = 1 ]; then
    python3 "${REPO_ROOT}/flow/common/make_timing_record.py" --pdk-root "${PDK_ROOT}"
  fi
  exit 0
fi

core_flow_setup
if [ "${NEG}" = 1 ]; then
  echo "== negative control: SHA256_NEG_SCRUB omits hh from the scrub list; test_scrub must fail =="
  core_flow_negctl_one sim-scrub-request.json SHA256_NEG_SCRUB scrub-negctl.json \
    "scrub negative control:" 'first failing scrub check: [^&]*' \
    "hh left out of the scrub"
  core_flow_negctl SHA256_NEG_CTRL "flips one K constant" "constant"
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
