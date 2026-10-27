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
#   ./verification/rtl/sha256/run.sh --negative-control # K[17] flipped by one bit: MUST fail
#                                                       # (exit 0 only if the bench catches it)
#
# Exit 0 only if the simulation passed and the synthesis is ok with no latches.
# Without --million-a that KAT is NOT run and a record says so. Synthesis is a
# single corner (tt_025C_1v80), pre-P&R, cell area only; no STA, no timing claim.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME=sha256
source "${HERE}/../../../flow/common/core_flow.sh"

RECORD=0; MILLION=0; NEG=0
for arg in "$@"; do
  case "${arg}" in
    --record) RECORD=1 ;;
    --million-a) MILLION=1 ;;
    --negative-control) NEG=1 ;;
    *) echo "unknown option: ${arg}" >&2; exit 2 ;;
  esac
done

core_flow_setup
[ "${NEG}" = 1 ] && core_flow_negctl "SHA256_NEG_CTRL flips one K constant" "constant"

core_flow_sim
rm -f "${OUT}/million.json"
if [ "${MILLION}" = 1 ]; then
  echo "== million-a KAT =="
  klt functional-verification sim-million-a-request.json --format json > "${OUT}/million.json"
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("million-a:", d["status"])' "${OUT}/million.json"
fi
core_flow_synth
core_flow_verdict "${RECORD}"
