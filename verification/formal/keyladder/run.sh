#!/usr/bin/env bash
#
# verification/formal/keyladder/run.sh -- slot properties of rtl/keyladder/keyladder.v
# (issue #56): P-5, P-6, P-2 and the module-boundary P-1, on the RTL and on the
# klt-synthesized sky130_fd_sc_hd netlist, each with a negative control.
#
#   ./scripts/setup-env.sh                       # once: .venv with klt, pinned yosys, sby, z3
#   ./verification/formal/keyladder/run.sh              # run everything, print the verdict
#   ./verification/formal/keyladder/run.sh --record     # same, then write a record under
#                                                       # verification/records/keyladder-formal/records/
#
# Exit 0 only if every property run meets its expectation (proofs pass, every negative
# control fails with a counterexample, every cover is reached, every mutation is
# registered). The bounded module-boundary P-1 runs may stop at a time limit: the depth
# they reached is recorded, which is not a failure; a counterexample is.
#
# Knobs (environment): PDK_ROOT, P1_DEPTH_RTL (24), P1_DEPTH_NET (10), P1_TIMEOUT_S (1500),
# P6_NET_DEPTH (2), PROVE_DEPTH (16). Solver runs are single-threaded, one at a time.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../../.." && pwd)"
STAGE="${REPO_ROOT}/flow/build/formal/keyladder"
PDK_ROOT="${PDK_ROOT:-${HOME}/.ciel}"
LIB="${PDK_ROOT}/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
P1_DEPTH_RTL="${P1_DEPTH_RTL:-24}"
P1_DEPTH_NET="${P1_DEPTH_NET:-10}"
P1_TIMEOUT_S="${P1_TIMEOUT_S:-1500}"
P6_NET_DEPTH="${P6_NET_DEPTH:-2}"
PROVE_DEPTH="${PROVE_DEPTH:-16}"

RECORD=0
for arg in "$@"; do
  case "${arg}" in
    --record) RECORD=1 ;;
    *) echo "unknown option: ${arg}" >&2; exit 2 ;;
  esac
done

for tool in klt sby yosys yosys-smtbmc z3; do
  if [ ! -x "${REPO_ROOT}/.venv/bin/${tool}" ]; then
    echo "error: ${REPO_ROOT}/.venv/bin/${tool} missing; run ./scripts/setup-env.sh first." >&2
    exit 1
  fi
done
[ -f "${LIB}" ] || { echo "error: liberty ${LIB} not found (PDK_ROOT)" >&2; exit 1; }
command -v iverilog >/dev/null || { echo "error: iverilog not on PATH" >&2; exit 1; }
# The venv's bin/ must lead $PATH so the pinned yosys, sby and z3 run, not host ones.
export PATH="${REPO_ROOT}/.venv/bin:${PATH}"

rm -rf "${STAGE}"
mkdir -p "${STAGE}"

# ---- 1. mutated RTL sources and the four synthesized netlists -------------------------
python3 "${HERE}/gen.py" --stage "${STAGE}" \
  --preprocess negmask=KL_NEG_MASK --preprocess neglock=KL_NEG_LOCK

synth() {  # synth NAME RTL_KEYLADDER
  local name="$1" kl="$2"
  local work="${STAGE}/synth_${name}"
  mkdir -p "${work}"
  python3 - "${work}" "${kl}" <<'PY'
import json, os, sys
work, kl = sys.argv[1], sys.argv[2]
root = os.environ["REPO_ROOT_FOR_PY"]
src = [os.path.join(root, "rtl/sha256/sha256_core.v"), os.path.join(root, "rtl/hmac/hmac_sha256.v"), kl]
json.dump({"schema": "klt.synthesize.request/1", "engine": "yosys",
           "sources": [os.path.relpath(s, work) for s in src], "hdl_toplevel": "keyladder",
           "pdk": {"cell_library": "sky130_fd_sc_hd", "corner": "tt_025C_1v80"},
           "constraints": {"clock_period_ns": None}},
          open(os.path.join(work, "synth-request.json"), "w"), indent=2)
PY
  (cd "${work}" && klt synthesize synth-request.json --pdk sky130A --pdk-root "${PDK_ROOT}" \
      --format json > synth.json)
  local rid
  rid="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "${work}/synth.json")"
  cp "${work}/.klt/synthesize/${rid}/keyladder_synth.v" "${STAGE}/net_${name}.v"
}
export REPO_ROOT_FOR_PY="${REPO_ROOT}"
echo "== synthesis (klt synthesize, tt_025C_1v80): clean + three mutants =="
synth clean "${REPO_ROOT}/rtl/keyladder/keyladder.v"
synth negmask "${STAGE}/rtl_negmask.v"
synth neglock "${STAGE}/rtl_neglock.v"
synth slotpath "${STAGE}/mut_slotpath.v"

python3 "${HERE}/gen.py" --stage "${STAGE}" \
  --netlist clean="${STAGE}/net_clean.v" --netlist negmask="${STAGE}/net_negmask.v" \
  --netlist neglock="${STAGE}/net_neglock.v" --netlist slotpath="${STAGE}/net_slotpath.v"

# ---- 1b. longest operation: one derivation's accept-to-done latency (Icarus) -----------
iverilog -o "${STAGE}/latency.vvp" "${HERE}/latency_tb.v" "${REPO_ROOT}/rtl/keyladder/keyladder.v" \
  "${REPO_ROOT}/rtl/hmac/hmac_sha256.v" "${REPO_ROOT}/rtl/sha256/sha256_core.v"
vvp "${STAGE}/latency.vvp" | tee "${STAGE}/latency.txt"

# ---- 2. P-2 structural cone check -----------------------------------------------------
echo "== P-2 / structural cone check =="
cd "${STAGE}"
cat > cone_tmpl_rtl.ys <<'YS'
read_verilog -sv @KL@ hmac_sha256.v sha256_core.v
hierarchy -top keyladder
proc
flatten
opt_clean
techmap
opt_clean
write_json @OUT@
YS
cat > cone_tmpl_net.ys <<YS
read_liberty -overwrite -ignore_miss_dir -ignore_miss_func ${LIB}
read_verilog @NET@
hierarchy -top keyladder
proc
flatten
opt_clean
write_json @OUT@
YS
cone() {  # cone NAME KIND(rtl|net) SOURCE EXPECT
  sed "s#@KL@#$3#; s#@NET@#$3#; s#@OUT@#cone_$1.json#" "cone_tmpl_$2.ys" > "cone_$1.ys"
  yosys -q -s "cone_$1.ys" > "cone_$1.yosys.log" 2>&1
  echo "-- $1 (expect $4)"
  python3 "${HERE}/cone.py" "cone_$1.json" --expect "$4" --out "cone_$1.result.json" || \
    echo "UNEXPECTED: cone check '$1' did not give '$4'"
}
cone rtl rtl keyladder.v pass
cone net net net_clean.v pass
cone rtl_slotpath rtl mut_slotpath.v fail
cone net_slotpath net net_slotpath.v fail

# ---- 3. SymbiYosys runs ---------------------------------------------------------------
for f in "${HERE}"/*.sby; do cp "${f}" "${STAGE}/"; done
sed -i "s#@DEPTH@#${PROVE_DEPTH}#; s#@DEPTH_P6_NET@#${P6_NET_DEPTH}#; \
        s#@DEPTH_RTL@#${P1_DEPTH_RTL}#; s#@DEPTH_NET@#${P1_DEPTH_NET}#; s#@LIB@#${LIB}#" ./*.sby
# P-1 bounded runs get a wall-clock limit (sby `timeout`, seconds) so the depth reached is
# recorded instead of the run hanging.
python3 - "${P1_TIMEOUT_S}" <<'PY'
import sys
t = sys.argv[1]
s = open("p1.sby").read()
s = s.replace("rtl: depth", f"rtl: timeout {t}\nnet: timeout {t}\nrtl: depth", 1)
open("p1.sby", "w").write(s)
PY

sby_run() {  # sby_run FILE TASK
  echo "-- sby $1 $2"
  local task="$2"; [ "${task}" = "-" ] && task=""   # "-": the .sby file defines no tasks
  sby -f "$1" ${task} > "$(basename "$1" .sby)_$2.out" 2>&1 || true
  grep -E "DONE \(" "$(basename "$1" .sby)_$2.out" | tail -1 || true
}
echo "== P-5 / P-6 (prove: BMC + k-induction, abstract HMAC) =="
for t in rtl neg_rtl net neg_net; do sby_run p5.sby "$t"; done
for t in rtl neg_rtl net neg_net; do sby_run p6.sby "$t"; done
sby_run cover.sby -
echo "== P-1 module boundary (2-copy BMC, real HMAC/SHA-256 core) =="
for t in cover neg_rtl neg_net rtl net; do sby_run p1.sby "$t"; done

# ---- 4. verdict (and record) ----------------------------------------------------------
cd "${REPO_ROOT}"
if [ "${RECORD}" = 1 ]; then
  python3 "${HERE}/make_record.py" --stage "${STAGE}" --pdk-root "${PDK_ROOT}" \
    --p1-depth-rtl "${P1_DEPTH_RTL}" --p1-depth-net "${P1_DEPTH_NET}" \
    --prove-depth "${PROVE_DEPTH}" --p6-net-depth "${P6_NET_DEPTH}"
else
  python3 "${HERE}/make_record.py" --stage "${STAGE}" --pdk-root "${PDK_ROOT}" --check-only \
    --p1-depth-rtl "${P1_DEPTH_RTL}" --p1-depth-net "${P1_DEPTH_NET}" \
    --prove-depth "${PROVE_DEPTH}" --p6-net-depth "${P6_NET_DEPTH}"
fi
