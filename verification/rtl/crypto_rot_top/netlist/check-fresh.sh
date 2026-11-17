#!/usr/bin/env bash
#
# verification/rtl/crypto_rot_top/netlist/check-fresh.sh -- freshness check for
# the committed crypto_rot_top gate-level netlist (issue #88).
#
# Re-runs the committed synthesis request (verification/rtl/crypto_rot_top/
# synthesize-request.json's sibling synth-request.json) in a scratch directory
# under the gitignored flow/build/ and byte-compares the fresh netlist against
# the committed crypto_rot_top_synth.v. The committed netlist is evidence only
# while it is what the pinned flow produces from the current RTL: this is the
# check that keeps it honest, and the `derived` freshness check of the item-1
# attestation inventory (manifests/inventories/item-1.json).
#
#   ./scripts/setup-env.sh                    # once: .venv (klt, pinned yosys)
#   ./verification/rtl/crypto_rot_top/netlist/check-fresh.sh
#
# Byte-compare (not a normalized one) is sound here: two clean `klt synthesize`
# runs of this request at different scratch paths produced byte-identical
# netlists (verified 2026-11-17, pinned klayout-tools 0.8.0 + yowasp-yosys
# 0.68.0.0.post1208, sky130A f6eeac7d; record
# verification/records/crypto-rot-top-netlist-formal/).
#
# Exit codes follow the `klt netlist --check` convention (docs/cli/netlist.md):
#   0  fresh -- the committed netlist is what the flow produces
#   3  stale -- an RTL edit (or a flow change) is not reflected in the
#      committed netlist; regenerate and commit it
#   other  hard error (missing tool/PDK/request, failed synthesis) -- not a
#      staleness verdict, never reported as one
#
# No security or side-channel claim is made here: this is a reproducibility
# statement about the committed artifact.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../../../.." && pwd)"
REQUEST="${HERE}/../synth-request.json"
COMMITTED="${HERE}/crypto_rot_top_synth.v"
ENVELOPE="${HERE}/synthesize-envelope.json"
STAGE="${REPO_ROOT}/flow/build/freshness/crypto_rot_top"
PDK_ROOT="${PDK_ROOT:-${HOME}/.ciel}"

fail() { echo "check-fresh: $*" >&2; exit "${2:-1}"; }

[ -f "${COMMITTED}" ] || fail "committed netlist ${COMMITTED} missing" 1
[ -f "${REQUEST}" ] || fail "synthesis request ${REQUEST} missing" 1
[ -x "${REPO_ROOT}/.venv/bin/klt" ] || fail "${REPO_ROOT}/.venv/bin/klt missing; run ./scripts/setup-env.sh first" 1
# The venv's bin/ must lead $PATH so klt runs the PINNED yosys (the yowasp
# wheel's byte-identical mapper), never a host yosys -- two hosts at the same
# nominal `yosys -V` have mapped the same design differently (2AMLogic/
# sky130-modexp#143); this check compares bytes.
export PATH="${REPO_ROOT}/.venv/bin:${PATH}"
LIB="${PDK_ROOT}/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
[ -f "${LIB}" ] || fail "liberty ${LIB} not found (PDK_ROOT=${PDK_ROOT})" 1

# The committed envelope pins the committed netlist's hash; drift there is a
# stale artifact before any synthesis is spent on it.
python3 - "${COMMITTED}" "${ENVELOPE}" <<'PY' || fail "committed netlist hash differs from synthesize-envelope.json's netlist_sha256 (envelope and netlist disagree)" 3
import hashlib, json, sys
net, env = sys.argv[1], sys.argv[2]
h = hashlib.sha256(open(net, "rb").read()).hexdigest()
pinned = json.load(open(env)).get("netlist_sha256", "")
# the response records bare hex; tolerate a "sha256:"-prefixed form too
sys.exit(0 if h == pinned.removeprefix("sha256:") else 1)
PY

# klayout-tools#5780: yosys's abc pass deadlocks when the temp path is long
# (yosys-abc's readline wraps the echoed `source' line), so synthesis runs
# with a pinned short TMPDIR.
TMP="$(mktemp -d /tmp/kltfreshXXXXXX)"
trap 'rm -rf "${TMP}"' EXIT
rm -rf "${STAGE}"
mkdir -p "${STAGE}"

# The committed request resolves its sources relative to its own directory;
# the scratch copy re-resolves them absolutely so the same RTL files are read.
python3 - "${REQUEST}" "${STAGE}/synth-request.json" <<'PY' || fail "could not stage the request" 1
import json, os, sys
src_req, dst = sys.argv[1], sys.argv[2]
req = json.load(open(src_req))
base = os.path.dirname(os.path.abspath(src_req))
req["sources"] = [os.path.abspath(os.path.normpath(os.path.join(base, s))) for s in req["sources"]]
json.dump(req, open(dst, "w"), indent=2)
PY

export TMPDIR="${TMP}"
(cd "${STAGE}" && "${REPO_ROOT}/.venv/bin/klt" synthesize synth-request.json \
    --pdk sky130A --pdk-root "${PDK_ROOT}" --format json > synth.json) \
  || fail "klt synthesize failed; see ${STAGE}/synth.json" 1

FRESH="$(python3 - "${STAGE}/synth.json" "${REPO_ROOT}" <<'PY'
import json, os, sys
d = json.load(open(sys.argv[1]))
if d.get("status") != "ok":
    raise SystemExit("synthesis status: " + str(d.get("status")))
np = d["netlist_path"]
if isinstance(np, dict):
    if np.get("scope") != "repo" or not np.get("path"):
        raise SystemExit("netlist_path is not repo-relative: " + json.dumps(np))
    print(os.path.join(sys.argv[2], np["path"]))
else:
    print(np)
PY
)" || fail "could not resolve the fresh netlist path" 1
[ -f "${FRESH}" ] || fail "fresh netlist ${FRESH} missing" 1

if cmp -s "${COMMITTED}" "${FRESH}"; then
  echo "check-fresh: fresh (byte-identical to the committed netlist)"
  exit 0
fi
echo "check-fresh: STALE -- the committed netlist is not what klt synthesize produces from the current RTL" >&2
echo "  regenerate: (cd ${STAGE} && klt synthesize synth-request.json --pdk sky130A --pdk-root ${PDK_ROOT})" >&2
echo "  then copy the fresh crypto_rot_top_synth.v over ${COMMITTED} and refresh synthesize-envelope.json" >&2
exit 3
