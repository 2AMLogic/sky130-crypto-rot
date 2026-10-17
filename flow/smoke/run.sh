#!/usr/bin/env bash
#
# flow/smoke/run.sh -- run the toolchain smoke flow in the pinned environment.
#
#   ./scripts/setup-env.sh          # once: provisions .venv, pinned yosys, PDK
#   ./flow/smoke/run.sh             # cocotb + Icarus on the RTL, then klt synthesize
#   ./flow/smoke/run.sh --record    # same, then write a record under
#                                   # verification/records/smoke-synthesis-sim/records/
#
# Exit 0 only if both the simulation and the synthesis passed. Single-corner
# `klt sta` is not run: it takes a routed DEF, which needs place-and-route
# (out of scope here, see docs/environment.md).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
OUT="${REPO_ROOT}/flow/build/smoke"
PDK_ROOT="${PDK_ROOT:-${HOME}/.ciel}"

if [ ! -x "${REPO_ROOT}/.venv/bin/klt" ]; then
  echo "error: ${REPO_ROOT}/.venv is not provisioned." >&2
  echo "  -> run ./scripts/setup-env.sh first." >&2
  exit 1
fi
# The venv's bin/ must lead $PATH so klt runs the pinned yosys, not a host one.
export PATH="${REPO_ROOT}/.venv/bin:${PATH}"

mkdir -p "${OUT}"
cd "${HERE}"

echo "== RTL simulation (klt functional-verification: cocotb + Icarus) =="
klt functional-verification sim-request.json --format json > "${OUT}/sim.json"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["status"], d["passed_count"], "/", d["test_count"], "tests")' "${OUT}/sim.json"

echo "== synthesis (klt synthesize -> sky130_fd_sc_hd, tt_025C_1v80) =="
# --pdk is explicit on purpose: a PDK root holding several families would
# otherwise resolve to whichever klt finds first (it picked gf180mcuA here).
klt synthesize synth-request.json --pdk sky130A --pdk-root "${PDK_ROOT}" \
  --format json > "${OUT}/synth.json"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["status"], d["instance_count"], "instances", d["area_um2"], "um2")' "${OUT}/synth.json"

if [ "${1:-}" = "--record" ]; then
  python3 "${HERE}/make_record.py" --out-dir "${OUT}" --pdk-root "${PDK_ROOT}"
else
  python3 "${HERE}/make_record.py" --out-dir "${OUT}" --pdk-root "${PDK_ROOT}" --check-only
fi
