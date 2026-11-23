#!/usr/bin/env bash
#
# flow/pnr/crypto_rot_top/run.sh -- place-and-route driver for the committed
# crypto_rot_top gate-level netlist (issue #295, the pre-route half of #47):
# the stale-netlist guard, then `klt place-and-route` bounded to the CTS
# stage -- floorplan (PDN preset sky130hd + tap cells, no scan insertion per
# spec/target-spec.md section 5) -> global/detailed placement -> clock-tree
# synthesis. The detailed route stays #47's: this script's bare `--record`
# is the full-route contract and refuses to start one locally by default
# (a local route measured 4.5-6 h wall, effectively single-threaded, and one
# attempt already outlived its step holding the output lock -- issue #47),
# naming the batch invocation that will run it once the klt pin allows
# single-unit batch dispatch.
#
#   ./scripts/setup-env.sh                          # once: .venv (klt, pinned yosys), PDK
#   ./flow/pnr/crypto_rot_top/run.sh --through-cts  # guard, then floorplan -> place -> CTS
#                                                    # (~25 min effectively single-threaded
#   ./flow/pnr/crypto_rot_top/run.sh --through-cts --record
#                                                  # same, plus an append-only record under
#                                                  # verification/records/crypto-rot-top-pnr/
#   ./flow/pnr/crypto_rot_top/run.sh --record      # the full-route contract (#47): explicit
#                                                  # `--backend batch` with batch.job_timeout_s
#                                                  # above the measured route time. Refused on
#                                                  # a pin without single-unit batch (klt 0.8.0
#                                                  # is one) with the gap named -- no local
#                                                  # route starts, nothing is recorded.
#   ./flow/pnr/crypto_rot_top/run.sh --record --local-full-route
#                                                  # deliberate manual opt-in: the full route
#                                                  # on THIS host (4.5-6 h wall). Not on any
#                                                  # automated path; run it in a window that
#                                                  # fits, and harvest the staged artifacts.
#
# Exit 0 only if the committed netlist passed its freshness check
# (verification/rtl/crypto_rot_top/netlist/check-fresh.sh -- a stale netlist
# must not silently produce fresh P&R evidence), the run reports status "ok"
# at exactly the requested target_stage, and the response's power-delivery
# audit of the DEF says "complete". No timing claim is made or graded: the
# response's slack fields are pre-route estimates recorded as data, and the
# spec section 7 timing rows stay "target, unmeasured" until STA (#50). No
# security claim: a placed design is not a secure one (spec section 8).
#
# klt anchors its scratch to the request file's own directory
# (.klt/place-and-route/, gitignored next to it): the committed request's
# runs scratch under layout/, this flow's derived stage-bounded and batch
# requests under flow/build/. The klt invocation always runs from the repo
# root so every path the engine touches sits inside the one tree a
# container-wrapped openroad could mount (the core_flow_sta convention).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Three directories below the repo root (flow/pnr/<design>/): ../../.. and
# not one less -- resolving REPO_ROOT one level short was the bug that made
# every invocation of #47's first --record attempt fail its own request
# check.
REPO_ROOT="$(cd "${HERE}/../../.." && pwd)"
REQUEST="layout/place-and-route.json"
NETLIST="verification/rtl/crypto_rot_top/netlist/crypto_rot_top_synth.v"
CHECK_FRESH="verification/rtl/crypto_rot_top/netlist/check-fresh.sh"
OUT="${REPO_ROOT}/flow/build/pnr/crypto_rot_top"
PDK_ROOT="${PDK_ROOT:-${HOME}/.ciel}"
# The full-route batch job timeout (#47's contract): the two measured route
# attempts ran 4h16m+ and 100+ min CPU without completing, so the detailed
# route alone is estimated at 4.5-6 h wall and pre-route adds ~25 min; 10 h
# sizes the whole job with headroom without letting a wedged job hold a
# fleet slot for a day.
ROUTE_JOB_TIMEOUT_S="${ROUTE_JOB_TIMEOUT_S:-36000}"

fail() { echo "pnr: $*" >&2; exit 1; }

_json_field() {  # _json_field <file> <python print expression over d>
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print('"$2"')' "$1"
}
_repo_path() {  # _repo_path <file> <field>: a {path, scope:"repo"} envelope's repo-relative path
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); p=d[sys.argv[2]];
print(p["path"] if isinstance(p, dict) and p.get("scope") == "repo" else "")' "$1" "$2"
}

THROUGH_CTS=0; RECORD=0; LOCAL_FULL_ROUTE=0
for arg in "$@"; do
  case "${arg}" in
    --through-cts) THROUGH_CTS=1 ;;
    --record) RECORD=1 ;;
    --local-full-route) LOCAL_FULL_ROUTE=1 ;;
    *) echo "unknown option: ${arg}" >&2; exit 2 ;;
  esac
done
if [ "$((THROUGH_CTS + RECORD + LOCAL_FULL_ROUTE))" -eq 0 ]; then
  echo "error: pick a mode: --through-cts (this issue's stage bound, with or" >&2
  echo "  without --record) or --record (the full-route contract; add" >&2
  echo "  --local-full-route only for a deliberate manual local route)." >&2
  exit 2
fi
if [ "${THROUGH_CTS}" = 1 ] && [ "${LOCAL_FULL_ROUTE}" = 1 ]; then
  echo "error: --through-cts and --local-full-route are mutually exclusive:" >&2
  echo "  --through-cts stops at CTS by construction; --local-full-route opts" >&2
  echo "  into #47's full detailed route on this host." >&2
  exit 2
fi
if [ "${LOCAL_FULL_ROUTE}" = 1 ] && [ "${RECORD}" = 0 ]; then
  echo "error: --local-full-route is an opt-in on --record, not a mode of its" >&2
  echo "  own: it names where the full route runs (here, not the batch fleet)." >&2
  echo "  Use --record --local-full-route." >&2
  exit 2
fi

[ -f "${REPO_ROOT}/${REQUEST}" ] || fail "request ${REQUEST} missing"
[ -x "${REPO_ROOT}/.venv/bin/klt" ] || fail "${REPO_ROOT}/.venv/bin/klt missing; run ./scripts/setup-env.sh first"
# The venv's bin/ must lead $PATH so klt runs the pinned tools, never host ones.
export PATH="${REPO_ROOT}/.venv/bin:${PATH}"
mkdir -p "${OUT}"

# _freshness -- the stale-netlist guard, first on every path that is about to
# start OpenROAD (issue #295 step 1: a stale netlist must not silently
# produce fresh P&R evidence), then the netlist hash every artifact of the
# run is bound to. Exit 3 is check-fresh's own staleness verdict.
_freshness() {
  echo "== netlist freshness (check-fresh.sh) =="
  local rc=0
  bash "${REPO_ROOT}/${CHECK_FRESH}" | tee "${OUT}/freshness.txt" || rc="${PIPESTATUS[0]}"
  if [ "${rc}" -eq 3 ]; then
    fail "committed netlist is STALE -- regenerate it before placing it"
  elif [ "${rc}" -ne 0 ]; then
    fail "check-fresh.sh failed (exit ${rc})"
  fi
  ( cd "${REPO_ROOT}" && sha256sum "${NETLIST}" )
}

# _derive_request <derived path> [key=json value ...] -- the ONE committed
# request is the contract (issue #295 curation); the stage bound and the
# batch block are derived into build scratch instead of tracking a second
# copy that can drift. The derivation must not lose the property the
# committed request has -- a tree-relative netlist path that resolves to the
# committed bytes -- so it is re-anchored to the derived document's own
# directory and verified against the committed netlist's hash here, before
# any OpenROAD starts on it.
_derive_request() {
  python3 - "${REPO_ROOT}/${REQUEST}" "$@" <<'PY'
import hashlib, json, os, sys
src, dst = sys.argv[1], sys.argv[2]
doc = json.load(open(src))
for kv in sys.argv[3:]:
    key, _, value = kv.partition("=")
    doc[key] = json.loads(value)
def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()
base = os.path.dirname(os.path.abspath(src))
resolved = doc["netlist"]
if not os.path.isabs(resolved):
    resolved = os.path.realpath(os.path.join(base, resolved))
root = os.path.dirname(os.path.dirname(os.path.abspath(src)))
committed = os.path.join(root, "verification", "rtl", "crypto_rot_top",
                         "netlist", "crypto_rot_top_synth.v")
if not os.path.isfile(resolved):
    raise SystemExit(f"pnr: the request's netlist {doc['netlist']!r} does not "
                     f"resolve from {src}")
if sha(resolved) != sha(committed):
    raise SystemExit(f"pnr: the request's netlist {doc['netlist']!r} is not "
                     f"the committed {committed}")
rel = os.path.relpath(committed, os.path.dirname(os.path.abspath(dst)))
doc["netlist"] = rel
os.makedirs(os.path.dirname(dst), exist_ok=True)
with open(dst, "w") as fh:
    json.dump(doc, fh, indent=2)
print(f"derived {os.path.relpath(dst, root)} "
      f"(netlist {rel}, verified same bytes as the committed netlist)")
PY
}

# _batch_capable -- exit 0 only if the INSTALLED klt accepts an explicit
# single-unit `--backend batch` place-and-route dispatch. A version number
# does not answer this (a pin bump by itself establishes nothing -- issue
# #295 curation), so the installed tree is probed directly:
# place_and_route_batch.resolve_backend is the exact gate
# `klt place-and-route --backend batch` passes through before any OpenROAD
# starts, and refuses single-unit batch dispatch on klt 0.8.0 (upstream
# 2AMLogic/klayout-tools#6897: the capability is on klt main but in no
# release; #6898: klt sets no OpenROAD thread count either, so even a
# capable pin routes this design effectively single-threaded).
_batch_capable() {
  "${REPO_ROOT}/.venv/bin/python3" - > /dev/null 2> "${OUT}/batch-probe.txt" <<'PY'
from klayout_tools import place_and_route_batch

place_and_route_batch.resolve_backend("batch", {}, units=1)
PY
}

# _check_response <stage> -- the response contract, refused rather than
# half-trusted: status "ok"; the run reached EXACTLY the requested stage (a
# run that stopped short must not be recorded as though it had not -- klt
# reports success for any stage at or beyond the target, so equality, not
# membership, is the check); power delivery "complete" in the response's own
# audit of the DEF. The timing figures print as what they are: pre-route
# estimates, data only (STA is #50).
_check_response() {
  local stage="$1" status placed
  _json_field "${OUT}/pnr.json" '"status:", d["status"], "stage_reached:", d["stage_reached"]'
  status="$(_json_field "${OUT}/pnr.json" 'd["status"]')"
  [ "${status}" = "ok" ] || fail "place-and-route did not complete (status ${status})"
  [ "$(_json_field "${OUT}/pnr.json" 'd["stage_reached"]')" = "${stage}" ] \
    || fail "run stopped at stage $(_json_field "${OUT}/pnr.json" 'd["stage_reached"]'), not ${stage}"
  _json_field "${OUT}/pnr.json" \
    '"  die", d["die_area_um2"], "um2, core", d["core_area_um2"], "um2, utilization", d["utilization_pct"], "%"'
  _json_field "${OUT}/pnr.json" \
    '"  worst setup slack", d.get("worst_slack_ns"), "ns (pre-route estimate, data only; STA is #50)"'
  placed="$(_json_field "${OUT}/pnr.json" 'd["power"]["placed"]["status"]')"
  [ "${placed}" = "complete" ] \
    || fail "power delivery incomplete in the audited DEF: $(_json_field "${OUT}/pnr.json" 'd["power"]["placed"].get("missing")')"
  _json_field "${OUT}/pnr.json" \
    '"  power delivery:", d["power"]["placed"]["status"], "(tapcells", d["power"]["placed"].get("tapcells"), "endcaps", d["power"]["placed"].get("endcaps"), "special_nets", d["power"]["placed"].get("special_nets"), ")"'
  _json_field "${OUT}/pnr.json" '"  warnings:", d["warnings"]'
}

# _stage_full_route_artifacts -- copy the routed GDS/DEF/post-route netlist
# and the response itself from scratch to their committed names under
# layout/, so a multi-hour route's output cannot rot in gitignored scratch.
# Staging is not a claim: no record, no envelope, no manifest citation
# happens here -- the route record and the item-2 attestation are #47's.
_stage_full_route_artifacts() {
  local gds def vlg
  gds="$(_repo_path "${OUT}/pnr.json" "gds_path")"
  def="$(_repo_path "${OUT}/pnr.json" "def_path")"
  vlg="$(_repo_path "${OUT}/pnr.json" "verilog_path")"
  [ -n "${gds}" ] && [ -f "${REPO_ROOT}/${gds}" ] || fail "routed GDS missing from the response"
  [ -n "${def}" ] && [ -f "${REPO_ROOT}/${def}" ] || fail "routed DEF missing from the response"
  [ -n "${vlg}" ] && [ -f "${REPO_ROOT}/${vlg}" ] || fail "post-route netlist missing from the response"
  echo "== staging the routed artifacts under layout/ =="
  cp "${REPO_ROOT}/${gds}" "${REPO_ROOT}/layout/crypto_rot_top.gds"
  cp "${REPO_ROOT}/${def}" "${REPO_ROOT}/layout/crypto_rot_top.def"
  cp "${REPO_ROOT}/${vlg}" "${REPO_ROOT}/layout/crypto_rot_top_pnr.v"
  cp "${OUT}/pnr.json" "${REPO_ROOT}/layout/place-and-route-envelope.json"
  echo "  route complete; staged layout/crypto_rot_top.{gds,def}, crypto_rot_top_pnr.v,"
  echo "  place-and-route-envelope.json. Remaining (#47): the route record and the"
  echo "  item-2 envelope + manifest citation -- neither is written by this issue."
}

if [ "${RECORD}" = 1 ] && [ "${THROUGH_CTS}" = 0 ] && [ "${LOCAL_FULL_ROUTE}" = 0 ]; then
  # The full-route contract. The capability refusal comes BEFORE the
  # freshness guard: refusing is a usage decision, not a run, and must not
  # spend two minutes of synthesis first.
  if ! _batch_capable; then
    {
      echo "  installed klt refuses single-unit batch place-and-route:"
      sed -e 's/^/    /' "${OUT}/batch-probe.txt" 2>/dev/null || true
    } >&2
    fail "the full detailed route (issue #47) cannot be dispatched from this host: an explicit single-unit --backend batch place-and-route is refused by the installed klt pin (2AMLogic/klayout-tools#6897 -- the capability exists on klt main but in no release this repo pins; 2AMLogic/klayout-tools#6898 -- klt sets no OpenROAD thread count, so the route stays effectively single-threaded either way). A local detailed route of this design measured 4.5-6 h wall (issue #47's two unfinished attempts) and one already outlived its step holding the output lock, so no local route is started by default. Deliberate manual run in a window that fits ~6 h: ./flow/pnr/crypto_rot_top/run.sh --record --local-full-route"
  fi
  _freshness
  echo "== full route (klt place-and-route --backend batch, job timeout ${ROUTE_JOB_TIMEOUT_S} s) =="
  _derive_request "${OUT}/route-batch-request.json" \
    "batch={\"job_timeout_s\": ${ROUTE_JOB_TIMEOUT_S}}"
  ( cd "${REPO_ROOT}" && klt place-and-route "${OUT}/route-batch-request.json" \
      --pdk sky130A --pdk-root "${PDK_ROOT}" --backend batch --format json ) \
    > "${OUT}/pnr.json"
  _check_response route
  _stage_full_route_artifacts
  exit 0
fi

if [ "${RECORD}" = 1 ] && [ "${LOCAL_FULL_ROUTE}" = 1 ]; then
  _freshness
  echo "== full route, LOCAL (deliberate manual opt-in: ~6 h wall, effectively single-threaded) =="
  ( cd "${REPO_ROOT}" && klt place-and-route "${REQUEST}" \
      --pdk sky130A --pdk-root "${PDK_ROOT}" --backend local --format json ) \
    > "${OUT}/pnr.json"
  _check_response route
  _stage_full_route_artifacts
  exit 0
fi

# --through-cts (with or without --record): the stage bound this issue lands.
_freshness
echo "== place-and-route through CTS (klt place-and-route, target_stage cts) =="
_derive_request "${OUT}/cts-request.json" 'target_stage="cts"'
( cd "${REPO_ROOT}" && klt place-and-route "${OUT}/cts-request.json" \
    --pdk sky130A --pdk-root "${PDK_ROOT}" --backend local --format json ) \
  > "${OUT}/pnr.json"
_check_response cts
CTS_DEF="$(_repo_path "${OUT}/pnr.json" "unrouted_def_path")"
[ -n "${CTS_DEF}" ] && [ -f "${REPO_ROOT}/${CTS_DEF}" ] \
  || fail "the CTS DEF is missing from the response (unrouted_def_path)"

if [ "${RECORD}" = 1 ]; then
  echo "== record (verification/records/crypto-rot-top-pnr/) =="
  python3 "${HERE}/make_record.py" --out-dir "${OUT}" --pdk-root "${PDK_ROOT}"
else
  echo "== scratch run only; --through-cts --record also writes the record =="
fi
