#!/usr/bin/env bash
#
# verification/rtl/trng_if/run.sh -- simulate rtl/trng_if/trng_if.v alone and
# inside drbg_top (DRBG + AES engine + interface), against a port-protocol stub
# of the sibling and against the sibling's own RTL at its pinned commit.
#
#   ./scripts/setup-env.sh                              # once: .venv, pinned yosys, PDK
#   ./verification/rtl/trng_if/run.sh                   # stub benches + real-sibling bench
#   ./verification/rtl/trng_if/run.sh --record          # same, then write a record under
#                                                       # verification/records/trng-if-sim/records/
#   ./verification/rtl/trng_if/run.sh --skip-real       # stub benches only (a record says so)
#   ./verification/rtl/trng_if/run.sh --negative-control  # five corrupted builds: every one MUST fail
#
# The sibling's RTL is fetched by fetch_trng.sh at the commit in reuse.lock.json
# and its sha256 is checked; it is never committed here. For the real-sibling
# bench its start-up length (16 samples), conditioner block (64 raw bits) and
# RCT cutoff (16) are shortened by parameter so the bench finishes; none of the
# behavior this block depends on (stream protocol, gated/startup_done/alarm,
# register map) changes.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME=trng_if
source "${HERE}/../../../flow/common/core_flow.sh"

RECORD=0; NEG=0; REAL=1
for arg in "$@"; do
  case "${arg}" in
    --record) RECORD=1 ;;
    --negative-control) NEG=1 ;;
    --skip-real) REAL=0 ;;
    *) echo "unknown option: ${arg}" >&2; exit 2 ;;
  esac
done

core_flow_setup
python3 -I mk_req.py

sim() { klt functional-verification "$1" --format json > "$2"; }
summaries() { grep -o 'SUMMARY[^<]*' .klt/functional-verification/test_icarus.log || true; }
status() { _json_line "$1" 'd["status"], d["passed_count"], "/", d["test_count"], "tests"'; }

if [ "${NEG}" = 1 ]; then
  echo "== negative controls: each corrupted build MUST fail =="
  bad=0
  for spec in "sim-if-negctl-prev-request.json:a word accepted after a gated previous sample" \
              "sim-if-negctl-discard-request.json:partial seed not discarded on gated" \
              "sim-if-negctl-count-request.json:seed one word short" \
              "sim-sys-negctl-zeroize-request.json:DRBG V survives the alarm zeroize" \
              "sim-sys-negctl-interval-request.json:one request too many before RESEED_REQUIRED"; do
    IFS=: read -r req label <<< "${spec}"
    if sim "${req}" "${OUT}/negctl.json"; then
      echo "FAIL: the bench passed with a corrupted build (${label})" >&2; bad=1
    else
      echo "negative control (${label}): bench failed as required"
      summaries | grep -v ' failures=0' | head -1 | cut -c1-220
    fi
  done
  exit "${bad}"
fi

echo "== trng_if alone vs the port-protocol stub (40:1 and 1000:1 clock ratios) =="
sim sim-if-request.json "${OUT}/if.json"; status "${OUT}/if.json"
summaries | tee "${OUT}/summary-if.txt"

echo "== drbg_top (trng_if + ctr_drbg + aes_core) vs the stub =="
sim sim-sys-request.json "${OUT}/sys.json"; status "${OUT}/sys.json"
summaries | tee "${OUT}/summary-sys.txt"

rm -f "${OUT}/real.json" "${OUT}/summary-real.txt"
if [ "${REAL}" = 1 ]; then
  echo "== drbg_top vs the sibling's RTL at its pinned commit =="
  ./fetch_trng.sh > "${OUT}/trng_path.txt"
  sim sim-real-request.json "${OUT}/real.json"; status "${OUT}/real.json"
  summaries | tee "${OUT}/summary-real.txt"
else
  echo "== real-sibling bench SKIPPED (--skip-real); a record will say so =="
fi

if [ "${RECORD}" = 1 ]; then
  python3 "${HERE}/make_record.py" --out-dir "${OUT}"
else
  python3 "${HERE}/make_record.py" --out-dir "${OUT}" --check-only
fi
