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
#                                                       # (the run stops at the first it does not)
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
# The eight sim-*-request.json files the benches below read are mk_req.py's
# output, not tracked copies of it: they are gitignored and rewritten on
# every run, and mk_req.py is the request input make_record.py hashes.
python3 -I mk_req.py

BENCH_LOG=.klt/functional-verification/test_icarus.log
# These benches assert with an unprefixed message, so what shows that the BENCH
# (not the build) failed is their own SUMMARY line with a non-zero failure count;
# the passing tests of the same elaboration log `failures=0` and do not match.
NEG_EVIDENCE='SUMMARY.*failures=[1-9][0-9]*'

sim() { klt functional-verification "$1" --format json > "$2"; }
summaries() { grep -o 'SUMMARY[^<]*' "${BENCH_LOG}" || true; }
status() { _json_line "$1" 'd["status"], d["passed_count"], "/", d["test_count"], "tests"'; }

if [ "${NEG}" = 1 ]; then
  echo "== negative controls: each corrupted build MUST fail =="
  core_flow_negctl_one sim-if-negctl-prev-request.json '' negctl-prev.json \
    "negative control (a word accepted after a gated previous sample):" "${NEG_EVIDENCE}" \
    "a word accepted after a gated previous sample" "${BENCH_LOG}"
  core_flow_negctl_one sim-if-negctl-discard-request.json '' negctl-discard.json \
    "negative control (partial seed not discarded on gated):" "${NEG_EVIDENCE}" \
    "a partial seed not discarded on gated" "${BENCH_LOG}"
  core_flow_negctl_one sim-if-negctl-count-request.json '' negctl-count.json \
    "negative control (seed one word short):" "${NEG_EVIDENCE}" \
    "a seed one word short" "${BENCH_LOG}"
  core_flow_negctl_one sim-sys-negctl-zeroize-request.json '' negctl-zeroize.json \
    "negative control (DRBG V survives the alarm zeroize):" "${NEG_EVIDENCE}" \
    "DRBG V surviving the alarm zeroize" "${BENCH_LOG}"
  core_flow_negctl_one sim-sys-negctl-interval-request.json '' negctl-interval.json \
    "negative control (one request too many before RESEED_REQUIRED):" "${NEG_EVIDENCE}" \
    "one request too many before RESEED_REQUIRED" "${BENCH_LOG}"
  exit 0
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
