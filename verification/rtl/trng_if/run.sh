#!/usr/bin/env bash
#
# verification/rtl/trng_if/run.sh -- simulate rtl/trng_if/trng_if.v alone and
# inside drbg_top (DRBG + AES engine + interface), against a port-protocol stub
# of the sibling and against the sibling's own RTL at its pinned commit.
#
#   ./scripts/setup-env.sh                              # once: .venv, pinned yosys, PDK
#   ./verification/rtl/trng_if/run.sh                   # stub benches + BOTH real-sibling benches
#   ./verification/rtl/trng_if/run.sh --record          # same, then write a record under
#                                                       # verification/records/trng-if-sim/records/
#   ./verification/rtl/trng_if/run.sh --skip-real       # stub benches only (a record says so)
#   ./verification/rtl/trng_if/run.sh --skip-real-full  # stub + shortened sibling only (ditto)
#   ./verification/rtl/trng_if/run.sh --negative-control  # five corrupted builds: every one MUST fail
#                                                       # (the run stops at the first it does not)
#
# The sibling's RTL is fetched by fetch_trng.sh at the commit in reuse.lock.json
# and its sha256 is checked; it is never committed here. It is then simulated
# TWICE against drbg_top, over the same fetched file:
#
#   real       -- start-up length (16 samples), conditioner block (64 raw bits)
#                 and RCT cutoff (16) shortened by parameter, which is what
#                 makes the alarm, recovery and negative-control cases
#                 affordable; none of the behavior this block depends on
#                 (stream protocol, gated/startup_done/alarm, register map)
#                 changes.
#   real-full  -- NO parameter overrides at all, so the start-up gate and the
#                 one-pop-per-sample-period handshake also run at the lengths
#                 the sibling's own RTL declares at the pin (issue #180). This
#                 is NOT opt-in: it measured 9-10 s here against about 18 min
#                 for scripts/cold-start-benches.sh as a whole, so the default
#                 run covers it and the record it writes claims it. The elapsed
#                 seconds are captured per run and quoted in the record, so a
#                 future pin that makes it expensive shows up as data.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME=trng_if
source "${HERE}/../../../flow/common/core_flow.sh"

SKIP_REAL=0; SKIP_REAL_FULL=0
# --skip-real drops BOTH sibling benches; --skip-real-full keeps the
# shortened one and drops only the unshortened pass.
CORE_FLOW_EXTRA_OPTS="--skip-real:SKIP_REAL --skip-real-full:SKIP_REAL_FULL"
CORE_FLOW_UNSUPPORTED="--sim-only"  # stops before a synthesis this core never runs
core_flow_parse_opts "$@"

core_flow_setup
# The nine sim-*-request.json files the benches below read are mk_req.py's
# output, not tracked copies of it: they are gitignored and rewritten on
# every run, and mk_req.py is the request input make_record.py hashes.
python3 -I mk_req.py

sim() { klt functional-verification "$1" --format json > "$2"; }

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
sim sim-if-request.json "${OUT}/if.json"; core_flow_status "${OUT}/if.json"
core_flow_summaries | tee "${OUT}/summary-if.txt"

echo "== drbg_top (trng_if + ctr_drbg + aes_core) vs the stub =="
sim sim-sys-request.json "${OUT}/sys.json"; core_flow_status "${OUT}/sys.json"
core_flow_summaries | tee "${OUT}/summary-sys.txt"

rm -f "${OUT}/real.json" "${OUT}/summary-real.txt"
if [ "${SKIP_REAL}" = 0 ]; then
  echo "== drbg_top vs the sibling's RTL at its pinned commit =="
  ./fetch_trng.sh > "${OUT}/trng_path.txt"
  sim sim-real-request.json "${OUT}/real.json"; core_flow_status "${OUT}/real.json"
  core_flow_summaries | tee "${OUT}/summary-real.txt"
else
  echo "== real-sibling bench SKIPPED (--skip-real); a record will say so =="
fi

rm -f "${OUT}/real-full.json" "${OUT}/summary-real-full.txt" "${OUT}/real-full-wall.txt"
if [ "${SKIP_REAL}" = 0 ] && [ "${SKIP_REAL_FULL}" = 0 ]; then
  echo "== drbg_top vs the sibling's RTL with NO parameter overrides =="
  # SECONDS is reset so the elapsed time below is this simulation alone; it is
  # the measured wall time make_record.py quotes, rather than hand-typed prose.
  SECONDS=0
  sim sim-real-full-request.json "${OUT}/real-full.json"
  echo "${SECONDS}" > "${OUT}/real-full-wall.txt"
  core_flow_status "${OUT}/real-full.json"
  echo "wall time: ${SECONDS} s"
  core_flow_summaries | tee "${OUT}/summary-real-full.txt"
else
  echo "== unshortened-sibling bench SKIPPED (--skip-real/--skip-real-full); a record will say so =="
fi

if [ "${RECORD}" = 1 ]; then
  python3 "${HERE}/make_record.py" --out-dir "${OUT}"
else
  python3 "${HERE}/make_record.py" --out-dir "${OUT}" --check-only
fi
