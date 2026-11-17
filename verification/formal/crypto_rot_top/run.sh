#!/usr/bin/env bash
#
# verification/formal/crypto_rot_top/run.sh -- the P-12 netlist re-proof for
# rtl/crypto_rot_top.v (issue #88), plus the top-level P-2, P-14 and the
# structural P-10 clear-term check, on the klt-synthesized sky130_fd_sc_hd
# netlist committed under verification/rtl/crypto_rot_top/netlist/.
#
#   ./scripts/setup-env.sh                                  # once: .venv (klt, pinned yosys, PDK)
#   ./verification/formal/crypto_rot_top/run.sh             # run every check, print the verdict
#   ./verification/formal/crypto_rot_top/run.sh --record    # same, then write a record under
#                                                           # verification/records/crypto-rot-top-netlist-formal/records/
#
# Exit 0 only if every check met its expectation:
#   * the committed netlist matches its committed synthesize envelope (hash),
#   * the P-12/P-2/P-14 structural checks PASS on the committed netlist
#     (cone_p12.py: every output port's cone excludes key-bearing registers
#     and the root_key/trng_out_data inputs, except dat_o's cone where the
#     three P-4 engine output carriers are cut; trng_bus_re constant;
#     plain-cell scopes; port list equal to the RTL's; P-10 clear terms),
#   * the committed flow log inserts no scan/DFT structure,
#   * the committed netlist is FRESH (check-fresh.sh re-synthesizes and
#     byte-compares; exit 0),
#   * and every negative control FAILS: a mutant RTL whose dat_o XORs
#     hmac_key bits into the read data, synthesized fresh (a key-to-output
#     path that does not go through a result window), must fail the P-12
#     check AND must differ byte-wise from the committed netlist (what the
#     freshness comparison catches); a spliced scan-flop scope
#     (sky130_fd_sc_hd__sdfxtp_1), a spliced probe-cell scope and a
#     spliced extra output port must each fail their structural check.
#
# No sby/solver runs here: these are structural checks (full sequential
# fan-in cones, "at every depth"), so nothing is bounded and no depth is
# reached. What the spec's N-properties mean at this level, and where the
# bounded module-level netlist proofs live, is stated per property in the
# record's coverage table (make_record.py).
#
# Knobs (environment): PDK_ROOT. Synthesis pins a short TMPDIR for the same
# reason as verification/formal/run.sh (yosys-abc readline deadlock on long
# temp paths, 2AMLogic/klayout-tools#5780).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../../.." && pwd)"
NETDIR="${REPO_ROOT}/verification/rtl/crypto_rot_top/netlist"
STAGE="${REPO_ROOT}/flow/build/formal/crypto-rot-top-netlist"
PDK_ROOT="${PDK_ROOT:-${HOME}/.ciel}"
LIB="${PDK_ROOT}/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"

RECORD=0
for arg in "$@"; do
  case "${arg}" in
    --record) RECORD=1 ;;
    *) echo "unknown option: ${arg}" >&2; exit 2 ;;
  esac
done

for tool in klt yosys; do
  [ -x "${REPO_ROOT}/.venv/bin/${tool}" ] || {
    echo "error: ${REPO_ROOT}/.venv/bin/${tool} missing; run ./scripts/setup-env.sh first." >&2; exit 1; }
done
[ -f "${LIB}" ] || { echo "error: liberty ${LIB} not found (PDK_ROOT=${PDK_ROOT})" >&2; exit 1; }
# The venv's bin/ must lead $PATH so the pinned yosys runs, not host ones
# (the same rule as verification/formal/keyladder/run.sh).
export PATH="${REPO_ROOT}/.venv/bin:${PATH}"

for f in crypto_rot_top_synth.v synthesize-envelope.json flow-log.ys check-fresh.sh; do
  [ -f "${NETDIR}/${f}" ] || { echo "error: committed evidence ${NETDIR}/${f} missing" >&2; exit 1; }
done

rm -rf "${STAGE}"
mkdir -p "${STAGE}"

echo "== envelope consistency (committed netlist hash == synthesize-envelope.json) =="
python3 - "${NETDIR}/crypto_rot_top_synth.v" "${NETDIR}/synthesize-envelope.json" "${STAGE}/envelope-check.json" <<'PY'
import hashlib, json, sys
net, env, out = sys.argv[1], sys.argv[2], sys.argv[3]
h = hashlib.sha256(open(net, "rb").read()).hexdigest()
d = json.load(open(env))
pinned = d.get("netlist_sha256", "").removeprefix("sha256:")
o = {"netlist_sha256": "sha256:" + h, "envelope_netlist_sha256": d.get("netlist_sha256"),
     "klt_version": d.get("provenance", {}).get("klt_version"),
     "pdk": d.get("provenance", {}).get("pdk", {}).get("version"),
     "deck": d.get("provenance", {}).get("deck", {}).get("name"),
     "instance_count": d.get("instance_count")}
o["match"] = h == pinned
json.dump(o, open(out, "w"), indent=2)
PY
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["match"], d' "${STAGE}/envelope-check.json" \
  || { echo "envelope: committed netlist does not match its envelope" >&2; exit 1; }
echo "  ok (klt $(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d["klt_version"])' "${STAGE}/envelope-check.json"), $(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d["instance_count"])' "${STAGE}/envelope-check.json") instances)"

echo "== flow-log check (no scan/DFT insertion in the recorded synthesis) =="
# every abc call must still EXCLUDE the special (low-power / probe) cell
# families, which is where a scan/test-capable cell could enter; and no line
# may mention scan/DFT/test insertion at all. (The abc call is recorded
# through a `tee -q -o ...` wrapper, so do not anchor at the line start.)
# The measured counts are written to flowlog-check.txt so the record's
# flow-log statement traces to these greps' outcome, not to a constant.
ABC_EXCL="$(grep -cE '(^| )abc .*-dont_use sky130_fd_sc_hd__lpflow_\* .*-dont_use sky130_fd_sc_hd__probe\*' "${NETDIR}/flow-log.ys" || true)"
[ "${ABC_EXCL}" -ge 1 ] || { echo "flow-log: abc does not exclude lpflow_*/probe* cells" >&2; exit 1; }
SDFT_HITS="$(grep -ciE 'scan|dft|\btest_|boundary|bscan' "${NETDIR}/flow-log.ys" || true)"
if [ "${SDFT_HITS}" != "0" ]; then
  echo "flow-log: scan/DFT-related token present in the recorded synthesis:" >&2
  grep -inE 'scan|dft|\btest_|boundary|bscan' "${NETDIR}/flow-log.ys" >&2
  exit 1
fi
{
  echo "flow-log: abc calls excluding lpflow_*/probe*: ${ABC_EXCL}"
  echo "flow-log: scan/DFT/boundary/test-token matches: ${SDFT_HITS}"
} > "${STAGE}/flowlog-check.txt"
echo "  ok (${ABC_EXCL} abc call(s) exclude lpflow_*/probe*, ${SDFT_HITS} scan/DFT tokens)"

echo "== flatten the committed netlist (yosys, liberty models) =="
NET_TMP="$(mktemp -d /tmp/kltp12XXXXXX)"
export TMPDIR="${NET_TMP}"
trap 'rm -rf "${NET_TMP}"' EXIT
flat() {  # flat <netlist.v> <out.json>
  cat > "${STAGE}/flat.ys" <<YS
read_liberty -overwrite -ignore_miss_dir -ignore_miss_func ${LIB}
read_verilog $1
hierarchy -check -top crypto_rot_top
flatten
opt_clean
write_json $2
YS
  (cd "${STAGE}" && yosys -q -s flat.ys)
}
flat "${NETDIR}/crypto_rot_top_synth.v" "${STAGE}/flat.json"
echo "  ok (flow/build/formal/crypto-rot-top-netlist/flat.json)"

echo "== P-12 / P-2 / P-14 / P-10 structural checks on the committed netlist =="
python3 "${HERE}/cone_p12.py" "${STAGE}/flat.json" --rtl "${REPO_ROOT}/rtl/crypto_rot_top.v" \
  --expect pass --out "${STAGE}/result_clean.json"

echo "== splice controls (each must make its structural check fail) =="
# primary control: a real mux-D scan flop (the cell family an actual DFT
# insertion maps flops to), not a token already known to the deny list
python3 "${HERE}/cone_p12.py" "${STAGE}/flat.json" \
  --splice-scope sky130_fd_sc_hd__sdfxtp_1 --expect fail --out "${STAGE}/result_ctrl_scan.json" \
  && echo "  ok: scan-flop cell scope control fails the cell check"
python3 "${HERE}/cone_p12.py" "${STAGE}/flat.json" \
  --splice-scope sky130_fd_sc_hd__probe_p_8 --expect fail --out "${STAGE}/result_ctrl_scope.json" \
  && echo "  ok: probe-cell scope control fails the cell check"
python3 "${HERE}/cone_p12.py" "${STAGE}/flat.json" --rtl "${REPO_ROOT}/rtl/crypto_rot_top.v" \
  --splice-port scan_out --expect fail --out "${STAGE}/result_ctrl_port.json" \
  && echo "  ok: extra-port control fails the port check"

echo "== freshness: the committed netlist is what the flow produces =="
if "${NETDIR}/check-fresh.sh" | tee "${STAGE}/freshness.txt"; then
  echo "  ok: fresh"
else
  rc=$?
  echo "check-fresh exited ${rc}" >&2
  exit 1
fi

echo "== negative control: mutant RTL with a key-to-output path (fresh synthesis) =="
# TOP_NEG_P12: dat_o XORs hmac_key bits into the read data -- a path from the
# slot registers to an output port that goes through NO result window. The
# edit is a source-mutated copy (klt synthesize takes no defines and no
# parameter overrides; the same pattern as verification/formal/gen_netlist.py).
sed 's/^    assign dat_o = viol ? 32'"'"'d0 : rdata;$/    assign dat_o = viol ? 32'"'"'d0 : (rdata ^ hmac_key[31:0]);/' \
  "${REPO_ROOT}/rtl/crypto_rot_top.v" > "${STAGE}/rtl_neg_p12.v"
MUT_LINES="$(grep -c 'rdata ^ hmac_key\[31:0\]' "${STAGE}/rtl_neg_p12.v")"
[ "${MUT_LINES}" = "1" ] || { echo "error: the dat_o mutation did not land exactly once (RTL line changed?)" >&2; exit 1; }
WORK="${STAGE}/synth_neg_p12"
mkdir -p "${WORK}"
REPO_ROOT_FOR_PY="${REPO_ROOT}" python3 - "${WORK}" "${STAGE}/rtl_neg_p12.v" <<'PY'
import json, os, sys
work, neg = sys.argv[1], sys.argv[2]
root = os.environ["REPO_ROOT_FOR_PY"]
srcs = ["rtl/sha256/sha256_core.v", "rtl/hmac/hmac_sha256.v", "rtl/keyladder/keyladder.v",
        "rtl/aes/aes_core.v", "rtl/drbg/ctr_drbg.v", "rtl/trng_if/trng_if.v",
        "rtl/drbg/drbg_top.v", neg]
json.dump({"schema": "klt.synthesize.request/1", "engine": "yosys",
           "sources": [os.path.relpath(s, work) if s.startswith("/") else os.path.relpath(os.path.join(root, s), work) for s in srcs],
           "hdl_toplevel": "crypto_rot_top",
           "pdk": {"cell_library": "sky130_fd_sc_hd", "corner": "tt_025C_1v80"},
           "constraints": {"clock_period_ns": None}},
          open(os.path.join(work, "synth-request.json"), "w"), indent=2)
PY
(cd "${WORK}" && klt synthesize synth-request.json --pdk sky130A --pdk-root "${PDK_ROOT}" \
    --format json > synth.json)
RID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "${WORK}/synth.json")"
cp "${WORK}/.klt/synthesize/${RID}/crypto_rot_top_synth.v" "${STAGE}/net_neg_p12.v"
echo "  synth neg_p12: run ${RID}"

echo "== freshness negative control: the mutant netlist must NOT byte-match the committed one =="
if cmp -s "${NETDIR}/crypto_rot_top_synth.v" "${STAGE}/net_neg_p12.v"; then
  echo "error: the mutant netlist is byte-identical to the committed netlist; the freshness comparison would not catch this edit" >&2
  exit 1
fi
echo "  ok: differs (the RTL edit is visible to the freshness check)"

echo "== P-12 structural checks on the mutant netlist (must fail) =="
flat "${STAGE}/net_neg_p12.v" "${STAGE}/flat_neg.json"
python3 "${HERE}/cone_p12.py" "${STAGE}/flat_neg.json" --rtl "${REPO_ROOT}/rtl/crypto_rot_top.v" \
  --expect fail --out "${STAGE}/result_neg.json" \
  && echo "  ok: the mutant fails the P-12 cone check"

echo "crypto-rot-top netlist formal: all checks met their expectation"
if [ "${RECORD}" = 1 ]; then
  python3 "${HERE}/make_record.py" --stage "${STAGE}" --pdk-root "${PDK_ROOT}"
fi
