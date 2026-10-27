#!/usr/bin/env bash
#
# scripts/setup-env.sh -- pin and provision this repo's verification
# environment.
#
# Adapted from 2AMLogic/sky130-modexp scripts/setup-env.sh at
# 18f4d8fd5e104f64550817a5468f262c159f734f (same PDK, same flow). The OpenROAD
# Docker fallback is dropped: openroad is only checked here, not provisioned.
#
#   1. Creates a local .venv (Python) and installs `klayout-tools` (`klt`)
#      into it at the pinned git revision below.
#   2. Installs the pinned Yosys build (YoWASP wheel) into that .venv and
#      verifies its WebAssembly module's sha256 -- the mapper identity that
#      `yosys -V` does NOT report (issue #143) -- then exposes it as
#      `.venv/bin/yosys`.
#   3. Fetches the pinned `sky130A` PDK version via `ciel` into
#      `${PDK_ROOT:-$HOME/.ciel}` and verifies the installed tree's open_pdks
#      revision (its `SOURCES` file) matches the pin.
#   4. Reports -- with an actionable message, never a Python traceback --
#      which of `iverilog`, `openroad` are missing from `$PATH`.
#
# Exit codes:
#   0  venv + klt + yosys + PDK provisioned. iverilog/openroad may still be
#      individually reported missing (see the toolchain check) -- this is
#      not itself a failure; see docs/environment.md.
#   1  venv creation, klt install, pinned-yosys install/verification, or PDK
#      fetch failed.
#
# Usage:
#   ./scripts/setup-env.sh
#   ./scripts/setup-env.sh --pdk-root /custom/path
#
# The resolved versions this script pins are recorded in
# docs/environment.md -- update both together if you re-pin.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}" || exit 1

# --- pinned versions -- keep in sync with docs/environment.md -------------
# Enforced by verification/check_pins.py (vendored by issue #6, wired into
# lint by issue #7):
# every constant in this block must appear in that doc's "Pinned versions"
# table. Keep assignments in plain NAME="value" form so it can parse them.
KLT_VERSION="0.8.0"
CIEL_VERSION="2.6.1"
COCOTB_VERSION="2.1.0"
CIEL_PDK_FAMILY="sky130"
CIEL_SKY130_VERSION="f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7"
# Yosys is pinned as a YoWASP PyPI wheel, not as a host package. The wheel is
# `py3-none-any` and ships a single WebAssembly module,
# `yowasp_yosys/yosys.wasm`, which contains Yosys *and* the `abc` mapper
# compiled into it -- so two hosts on the same pinned version execute a
# byte-identical mapper. A host-built `yosys` does not have that property:
# `yosys -V` names the Yosys version but says nothing about the embedded abc
# build, and issue #141 measured two hosts at the same nominal `yosys -V`
# mapping the same design to 1204 vs. 1105 instances. So the pin below is
# checked by CONTENT (the wasm sha256), not by version string.
YOWASP_YOSYS_VERSION="0.68.0.0.post1208"
YOWASP_YOSYS_WASM_SHA256="e37a7e65e3fa4efbbd64a9c1b0e906be16cdc6c4d5273109d17537f78449f38c"
# Formal flow (issue #56). SymbiYosys (`sby`), `yosys-smtbmc` and `yosys-witness`
# ship inside the pinned YoWASP wheel above (entry points yowasp-sby,
# yowasp-yosys-smtbmc, yowasp-yosys-witness), so they are pinned by the same
# wasm digest. The SMT solver is the PyPI `z3-solver` wheel, which carries a
# native `z3` binary; it is pinned by version and checked by the sha256 of that
# binary (the solver identity `z3 --version` does not fully name).
Z3_SOLVER_VERSION="5.3.2.0"
Z3_BIN_SHA256="c45e787b5d1a3d94079d1e83b98e23bbc884ccaf542ea38c3814f31ac2f79197"
# ----------------------------------------------------------------------------

PDK_ROOT="${PDK_ROOT:-${HOME}/.ciel}"
VENV_DIR="${REPO_ROOT}/.venv"

for arg in "$@"; do
  case "${arg}" in
    --pdk-root)
      echo "error: --pdk-root requires a value, e.g. --pdk-root=/path" >&2
      exit 1
      ;;
    --pdk-root=*)
      PDK_ROOT="${arg#--pdk-root=}"
      ;;
    -h|--help)
      sed -n '2,34p' "${BASH_SOURCE[0]}"
      exit 0
      ;;
    *)
      echo "unknown option: ${arg}" >&2
      exit 1
      ;;
  esac
done

status=0

echo "== 1/4 python venv =="
# cocotb 2.x refuses to build on Python > 3.13 with a
# RuntimeError, not a graceful skip -- pick a compatible interpreter up
# front so that failure surfaces here, as an actionable message, rather
# than as a pip build-backend traceback in step 2.
PYTHON_BIN=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  found="$(command -v "${candidate}" || true)"
  if [ -z "${found}" ]; then
    continue
  fi
  ver="$("${found}" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null)"
  major="${ver%%.*}"
  minor="${ver##*.}"
  if [ "${major}" = "3" ] && [ "${minor}" -le 13 ] 2>/dev/null; then
    PYTHON_BIN="${found}"
    break
  fi
done

if [ -z "${PYTHON_BIN}" ]; then
  echo "FATAL: no Python <= 3.13 interpreter found on \$PATH."
  echo "  cocotb ${COCOTB_VERSION} (pinned here)"
  echo "  refuses to build on Python 3.14+."
  echo "  -> install a compatible interpreter, e.g.:"
  echo "       brew install python@3.13   (macOS/Homebrew)"
  echo "       uv python install 3.13     (if 'uv' is available)"
  echo "       apt-get install python3.13 (Debian/Ubuntu with deadsnakes/backports)"
  echo "     then re-run this script; it prefers python3.13 > 3.12 > 3.11 >"
  echo "     3.10 > plain python3 automatically once one exists on \$PATH."
  exit 1
fi
echo "python3: $(${PYTHON_BIN} --version 2>&1) (${PYTHON_BIN})"

if [ ! -d "${VENV_DIR}" ]; then
  if ! "${PYTHON_BIN}" -m venv "${VENV_DIR}" >/dev/null 2>&1; then
    # A failed `venv` leaves a half-built directory that a re-run would
    # mistake for a usable venv; clear it before trying anything else.
    rm -rf "${VENV_DIR}"
    if command -v uv >/dev/null 2>&1 \
        && uv venv --seed --python "${PYTHON_BIN}" "${VENV_DIR}" >/dev/null 2>&1; then
      echo "note: ${PYTHON_BIN} has no venv/ensurepip module; used 'uv venv --seed'."
    else
      rm -rf "${VENV_DIR}"
      echo "FATAL: could not create ${VENV_DIR} with ${PYTHON_BIN}."
      echo "  -> on Debian/Ubuntu this usually means the venv module is"
      echo "     missing: 'apt-get install python3-venv' (needs an admin; this"
      echo "     script never runs apt itself), or install 'uv' and re-run."
      exit 1
    fi
  fi
  echo "created ${VENV_DIR}"
else
  echo "reusing existing ${VENV_DIR}"
fi

VENV_PY="${VENV_DIR}/bin/python3"
VENV_PIP="${VENV_DIR}/bin/pip"
if [ ! -x "${VENV_PY}" ]; then
  echo "FATAL: ${VENV_PY} not found after venv creation -- venv looks corrupt."
  echo "  -> remove ${VENV_DIR} and re-run this script."
  exit 1
fi

echo
echo "== 2/4 klayout-tools (klt) ${KLT_VERSION} =="
if ! "${VENV_PY}" -m pip --version >/dev/null 2>&1; then
  echo "FATAL: pip is not available inside ${VENV_DIR}."
  echo "  -> remove ${VENV_DIR} and re-run this script (venv bootstrap likely"
  echo "     failed partway through)."
  exit 1
fi

if ! "${VENV_PIP}" install --quiet --upgrade pip; then
  echo "WARNING: could not upgrade pip in ${VENV_DIR}; continuing with the"
  echo "  version venv bundled."
fi

if ! "${VENV_PIP}" install --quiet \
    "klayout-tools==${KLT_VERSION}" "cocotb==${COCOTB_VERSION}" "ciel==${CIEL_VERSION}"; then
  echo "FATAL: failed to install klayout-tools/cocotb/ciel into ${VENV_DIR}."
  echo "  -> common causes: no network access to PyPI, or no C/C++"
  echo "     toolchain for a dependency's native build (install Xcode CLI"
  echo "     tools on macOS: 'xcode-select --install'; build-essential on"
  echo "     Debian/Ubuntu)."
  echo "  -> re-run with the venv's own pip for a full traceback:"
  echo "       ${VENV_PIP} install \"klayout-tools==${KLT_VERSION}\" cocotb==${COCOTB_VERSION} ciel==${CIEL_VERSION}"
  exit 1
fi
INSTALLED_KLT_VERSION="$("${VENV_PY}" -m klayout_tools.cli --version 2>/dev/null || true)"
INSTALLED_KLT_VERSION="${INSTALLED_KLT_VERSION#klt }"
echo "installed: klt ${INSTALLED_KLT_VERSION:-(version unknown)} (pinned ${KLT_VERSION})"
echo "activate with: source ${VENV_DIR}/bin/activate"

echo
echo "== 3/4 yosys (YoWASP ${YOWASP_YOSYS_VERSION}) =="
# Why a wheel and not the host's `yosys`: see the pin block at the top of this
# file. The check below is the load-bearing half -- it verifies the *content*
# of the WebAssembly module (Yosys + its embedded `abc`), which is the mapper
# identity `yosys -V` does not expose.
if ! "${VENV_PIP}" install --quiet "yowasp-yosys==${YOWASP_YOSYS_VERSION}"; then
  echo "FATAL: failed to install yowasp-yosys==${YOWASP_YOSYS_VERSION} into ${VENV_DIR}."
  echo "  -> common causes: no network access to PyPI, or a proxy that"
  echo "     rejects the ~40 MB wheel download."
  echo "  -> re-run with the venv's own pip for a full traceback:"
  echo "       ${VENV_PIP} install \"yowasp-yosys==${YOWASP_YOSYS_VERSION}\""
  exit 1
fi

WASM_INFO="$("${VENV_PY}" - <<'PY'
import hashlib
import os
import sys

try:
    import yowasp_yosys
except Exception as exc:  # pragma: no cover - reported, never raised at user
    print(f"ERROR\t{exc}")
    sys.exit(0)

path = os.path.join(os.path.dirname(yowasp_yosys.__file__), "yosys.wasm")
if not os.path.isfile(path):
    print(f"ERROR\tno yosys.wasm at {path}")
    sys.exit(0)

digest = hashlib.sha256()
with open(path, "rb") as handle:
    for chunk in iter(lambda: handle.read(1 << 20), b""):
        digest.update(chunk)
print(f"OK\t{path}\t{digest.hexdigest()}")
PY
)"

case "${WASM_INFO}" in
  OK*)
    WASM_PATH="$(printf '%s' "${WASM_INFO}" | cut -f2)"
    WASM_SHA="$(printf '%s' "${WASM_INFO}" | cut -f3)"
    ;;
  *)
    echo "FATAL: could not locate the installed YoWASP Yosys WebAssembly module."
    echo "  detail: $(printf '%s' "${WASM_INFO}" | cut -f2-)"
    echo "  -> remove ${VENV_DIR} and re-run this script."
    exit 1
    ;;
esac

if [ "${WASM_SHA}" != "${YOWASP_YOSYS_WASM_SHA256}" ]; then
  echo "FATAL: pinned Yosys/ABC build identity does NOT match."
  echo "  module:   ${WASM_PATH}"
  echo "  expected: sha256:${YOWASP_YOSYS_WASM_SHA256}"
  echo "  actual:   sha256:${WASM_SHA}"
  echo "  -> this is exactly the failure the pin exists to catch: a different"
  echo "     mapper build maps the same RTL to a different instance count and"
  echo "     can move a timing-closure verdict across the threshold (issue"
  echo "     #141 measured 1.06 ns of setup slack at ss_n40C_1v28). Do NOT"
  echo "     mint evidence records from this environment."
  echo "  -> re-pin deliberately (update YOWASP_YOSYS_VERSION and"
  echo "     YOWASP_YOSYS_WASM_SHA256 here and the matching row in"
  echo "     docs/environment.md together), or remove ${VENV_DIR} and re-run."
  exit 1
fi
echo "yosys.wasm: sha256:${WASM_SHA} (matches pin)"

# Expose the pinned build under the plain name `yosys`: klt shells out to
# `yosys` by name (klayout_tools/synthesize.py runs `["yosys", "-s", script]`),
# so after `source .venv/bin/activate` the venv's bin/ leads $PATH and the
# pinned build wins over any host install.
if ! ln -sfn "yowasp-yosys" "${VENV_DIR}/bin/yosys"; then
  echo "FATAL: could not link ${VENV_DIR}/bin/yosys -> yowasp-yosys."
  exit 1
fi
echo "linked:     ${VENV_DIR}/bin/yosys -> yowasp-yosys"
echo "reports:    $("${VENV_DIR}/bin/yosys" -V 2>&1 | head -1)"
# SymbiYosys and its helpers come from the same pinned wheel (see pin block).
for pair in "sby:yowasp-sby" "yosys-smtbmc:yowasp-yosys-smtbmc" "yosys-witness:yowasp-yosys-witness"; do
  if ! ln -sfn "${pair#*:}" "${VENV_DIR}/bin/${pair%%:*}"; then
    echo "FATAL: could not link ${VENV_DIR}/bin/${pair%%:*} -> ${pair#*:}."
    exit 1
  fi
done
echo "linked:     sby, yosys-smtbmc, yosys-witness (from the same wheel)"
if ! "${VENV_PIP}" install --quiet "z3-solver==${Z3_SOLVER_VERSION}"; then
  echo "FATAL: failed to install z3-solver==${Z3_SOLVER_VERSION} into ${VENV_DIR}."
  exit 1
fi
Z3_SHA="$(sha256sum "${VENV_DIR}/bin/z3" 2>/dev/null | cut -d' ' -f1)"
if [ "${Z3_SHA}" != "${Z3_BIN_SHA256}" ]; then
  echo "FATAL: pinned z3 binary identity does NOT match."
  echo "  expected: sha256:${Z3_BIN_SHA256}"
  echo "  actual:   sha256:${Z3_SHA:-(missing)}"
  echo "  -> do NOT mint formal records from this environment; re-pin"
  echo "     Z3_SOLVER_VERSION/Z3_BIN_SHA256 here and in docs/environment.md together."
  exit 1
fi
echo "z3:         $("${VENV_DIR}/bin/z3" --version 2>&1 | head -1) (sha256:${Z3_SHA:0:12}... matches pin)"
if command -v yosys >/dev/null 2>&1; then
  echo "note: a host 'yosys' is also on \$PATH ($(command -v yosys)). It is NOT"
  echo "  the pinned build unless it resolves to the link above -- activate the"
  echo "  venv ('source ${VENV_DIR}/bin/activate') before running"
  echo "  'klt synthesize', or the mapper that produced your numbers is"
  echo "  unidentified."
fi

echo
echo "== 4/4 sky130A PDK (ciel ${CIEL_VERSION}, open_pdks ${CIEL_SKY130_VERSION:0:12}) =="
mkdir -p "${PDK_ROOT}"
if "${VENV_DIR}/bin/ciel" enable \
    --pdk-root "${PDK_ROOT}" --pdk-family "${CIEL_PDK_FAMILY}" \
    -l sky130_fd_pr "${CIEL_SKY130_VERSION}"; then
  # Verify the tree we will actually use IS the pinned open_pdks revision: its
  # SOURCES file names the revision it was built from. A missing or different
  # revision is a hard failure, never a silent pass -- a stray tree (e.g. a
  # leftover ~/.volare at the previous pin) must not stand in for the pin.
  SOURCES_FILE="${PDK_ROOT}/sky130A/SOURCES"
  if [ ! -f "${SOURCES_FILE}" ]; then
    echo "FATAL: ${SOURCES_FILE} not found; cannot verify the open_pdks revision."
    status=1
  elif ! grep -q "${CIEL_SKY130_VERSION}" "${SOURCES_FILE}"; then
    echo "FATAL: PDK revision mismatch under ${PDK_ROOT}: ${SOURCES_FILE} does not"
    echo "  name the pinned open_pdks ${CIEL_SKY130_VERSION}. It says:"
    sed 's/^/    /' "${SOURCES_FILE}"
    status=1
  else
    echo "sky130A ready under ${PDK_ROOT} (open_pdks ${CIEL_SKY130_VERSION:0:12} verified via SOURCES)"
  fi
else
  echo "FATAL: 'ciel enable' failed to fetch sky130 ${CIEL_SKY130_VERSION:0:12}."
  echo "  -> common causes: no network access to GitHub releases, or a rate"
  echo "     limit on unauthenticated GitHub API requests -- set GITHUB_TOKEN"
  echo "     and re-run, or run manually:"
  echo "       ${VENV_DIR}/bin/ciel enable --pdk-root ${PDK_ROOT} --pdk-family ${CIEL_PDK_FAMILY} -l sky130_fd_pr ${CIEL_SKY130_VERSION}"
  status=1
fi

echo
echo "== toolchain check (iverilog / openroad) =="
# yosys is NOT probed here: step 3 provisions it into the venv at a pinned,
# digest-verified build. A host `yosys` on $PATH is not that build (issue
# #143), so "some yosys resolves" is not the property this check should
# report.
echo "  yosys:    ${VENV_DIR}/bin/yosys (pinned, verified in step 3)"
missing=()
if command -v iverilog >/dev/null 2>&1; then
  echo "  iverilog: $(iverilog -V 2>&1 | head -1)"
else
  missing+=("iverilog")
fi

if command -v openroad >/dev/null 2>&1; then
  echo "  openroad: $(openroad -version 2>&1 | head -1) (native, on \$PATH)"
else
  missing+=("openroad")
fi

if [ "${#missing[@]}" -gt 0 ]; then
  echo
  echo "MISSING TOOLS: ${missing[*]}"
  for tool in "${missing[@]}"; do
    case "${tool}" in
      iverilog)
        echo "  - iverilog (Icarus Verilog): 'brew install icarus-verilog' (macOS)"
        echo "    or 'apt-get install iverilog' (Debian/Ubuntu). Required for"
        echo "    the cocotb + Icarus smoke test."
        ;;
      openroad)
        echo "  - openroad: no package-manager formula on macOS or common Linux"
        echo "    distros. Build from https://github.com/The-OpenROAD-Project/OpenROAD"
        echo "    and put it on \$PATH. Required for 'klt place-and-route'/'klt sta'"
        echo "    only; the smoke flow's synthesis and simulation do not need it."
        ;;
    esac
  done
  echo
  echo "This is non-fatal for this script: the smoke flow (flow/smoke/run.sh)"
  echo "needs only iverilog plus the pinned venv tools."
else
  echo "all of iverilog/yosys/openroad resolve (yosys from the pin above)."
fi

echo
if [ "${status}" -eq 0 ]; then
  echo "RESULT: environment provisioned (venv + klt + pinned yosys + sky130A)."
else
  echo "RESULT: environment provisioning incomplete -- see FATAL messages above."
fi
exit "${status}"
