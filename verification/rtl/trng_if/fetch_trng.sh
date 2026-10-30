#!/usr/bin/env bash
#
# verification/rtl/trng_if/fetch_trng.sh -- fetch the sibling's RTL at the pin
# in reuse.lock.json into flow/build/trng/ and check its sha256 against the
# lock. The file is never committed here (mode "fetched"). Exit 0 and print the
# path on success; exit 1 if it cannot be fetched or the hash differs.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
OUT="${REPO_ROOT}/flow/build/trng"
mkdir -p "${OUT}"
read -r COMMIT UPSTREAM SHA < <(python3 -I - "${REPO_ROOT}/reuse.lock.json" <<'PY'
import json, sys
lock = json.load(open(sys.argv[1]))
imp = next(i for i in lock["imports"] if i["from"] == "2AMLogic/sky130-trng")
f = next(f for f in imp["files"] if f["upstream"].endswith("trng_digital.v"))
print(imp["commit"], f["upstream"], f["sha256"])
PY
)
DEST="${OUT}/trng_digital.v"
if ! { [ -f "${DEST}" ] && [ "$(sha256sum "${DEST}" | cut -d' ' -f1)" = "${SHA}" ]; }; then
  gh api "repos/2AMLogic/sky130-trng/contents/${UPSTREAM}?ref=${COMMIT}" \
    -H "Accept: application/vnd.github.raw" > "${DEST}.tmp"
  mv "${DEST}.tmp" "${DEST}"
fi
GOT="$(sha256sum "${DEST}" | cut -d' ' -f1)"
if [ "${GOT}" != "${SHA}" ]; then
  echo "error: ${DEST} sha256 ${GOT} != reuse.lock.json ${SHA}" >&2
  exit 1
fi
echo "${DEST}"
