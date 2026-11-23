#!/usr/bin/env bash
#
# verification/formal/measure_engines.sh -- engine and trace measurement for
# the P-7/P-8/P-9 RTL formal tasks (issue #309). Measurement only: this
# script never edits a committed .sby, property, wrapper, depth or expect
# line, and writes no record under verification/records/. Its output feeds
# verification/formal/engine-measurement.md, the report with the engine
# recommendation.
#
# Three passes over the ten RTL tasks of p7_p8.sby + p9.sby:
#
#   base  the committed .sby files exactly as run.sh runs them (abc pdr /
#         abc bmc3, aigsmt none) -- a fresh baseline on this machine and
#         commit, not the one quoted from the 2026-11-15 record.
#   aig   trace conversion: copies of the two .sby files under the build
#         area with the single change `aigsmt none` -> `aigsmt z3` (engines,
#         depths, properties untouched). Expected-FAIL tasks should now
#         produce a VCD counterexample via z3 + yosys-witness.
#   smt   solver coverage: copies with every engine line changed to
#         `smtbmc z3` (modes/depths untouched; bounded tasks at their
#         committed depth, the two prove tasks as smtbmc induction) and a
#         600 s per-task timeout. A task hitting the cap is recorded as
#         TIMEOUT, never PASS/FAIL.
#
# Usage (after ./scripts/setup-env.sh):
#   ./verification/formal/measure_engines.sh
#
# Output: flow/build/formal/engine-measurement/results.tsv (tab-separated:
# pass, file, task, status, sby exit code, engine summary line, failing
# frame, elapsed seconds, trace) plus one sby task directory per row. The
# runs are sequential (one sby at a time; shared host).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
OUT="${REPO_ROOT}/flow/build/formal/engine-measurement"

SBY="${REPO_ROOT}/.venv/bin/sby"
if [ ! -x "${SBY}" ]; then
  echo "error: ${SBY} not found." >&2
  echo "  -> run ./scripts/setup-env.sh first." >&2
  exit 2
fi
if ! command -v yosys-abc > /dev/null 2>&1; then
  echo "error: yosys-abc not found on PATH (the base and aig passes need it)." >&2
  exit 2
fi
export PATH="${REPO_ROOT}/.venv/bin:${PATH}"

rm -rf "${OUT}"
mkdir -p "${OUT}"

# ---- variant copies under the build area ---------------------------------
# sby resolves [files] entries against the directory it runs from, so the
# copies live directly under ${OUT} (four levels below the repo root) and
# re-point the source paths at the committed tree. Only the lines named in
# the header comment differ from the committed files.
rewrite_paths() { # rewrite_paths <sby-text-on-stdin > sby-text-on-stdout
  sed -e 's#^\.\./\.\./rtl/#../../../../rtl/#' \
      -e 's#^fv_drbg\.v$#../../../../verification/formal/fv_drbg.v#' \
      -e 's#^fv_p9\.v$#../../../../verification/formal/fv_p9.v#'
}

for f in p7_p8.sby p9.sby; do
  rewrite_paths < "${HERE}/${f}" \
    | sed -e 's#^aigsmt none#aigsmt z3#' > "${OUT}/${f%.sby}.aig.sby"
  rewrite_paths < "${HERE}/${f}" \
    | sed -e 's#^\([a-z_]*\): abc pdr#\1: smtbmc z3#' \
          -e 's#^\([a-z_]*\): abc bmc3#\1: smtbmc z3#' \
          -e 's#^aigsmt none#aigsmt z3\ntimeout 600#' > "${OUT}/${f%.sby}.smt.sby"
done

# ---- runner ---------------------------------------------------------------
RESULTS="${OUT}/results.tsv"
: > "${RESULTS}"

run_one() { # run_one <pass> <sby-dir-cd> <file.sby-to-run> <task> <file-label>
  local pass="$1" rundir="$2" file="$3" task="$4" label="$5"
  local base="${label%.sby}"
  local dir="${OUT}/${pass}_${base}_${task}" rc=0
  rm -rf "${dir}"
  ( cd "${rundir}" && "${SBY}" -f -d "${dir}" "${file}" "${task}" \
      > "${OUT}/${pass}_${base}_${task}.out" 2>&1 ) || rc=$?
  local status engine frame secs trace
  # logfile.txt is missing when sby dies early; every grep tolerates that so
  # a row is always written (a missing tool is a tool-failure row, not a
  # solver verdict).
  status="$(grep -o 'DONE ([A-Z]*' "${dir}/logfile.txt" 2>/dev/null | tail -1 | sed 's/DONE (//' || true)"
  engine="$(grep -o 'summary: engine_0 ([a-z0-9 ]*) returned [A-Z]*' "${dir}/logfile.txt" 2>/dev/null | tail -1 | sed 's/summary: //' || true)"
  frame="$(grep -o 'asserted in frame [0-9]*' "${dir}/logfile.txt" 2>/dev/null | head -1 | grep -o '[0-9]*$' || true)"
  secs="$(grep -o 'Elapsed clock time.*(\([0-9]*\))' "${dir}/logfile.txt" 2>/dev/null | tail -1 | grep -o '([0-9]*)' | tr -d '()' || true)"
  trace="n/a"
  if [ -d "${dir}/engine_0" ]; then
    local t
    t="$(find "${dir}/engine_0" -maxdepth 1 -name 'trace*.vcd' -size +0 2>/dev/null | sort | head -1 || true)"
    if [ -n "${t}" ]; then trace="yes ${t}"; else trace="no"; fi
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "${pass}" "${file}" "${task}" "${status:-ERROR}" "${rc}" \
    "${engine:-none}" "${frame:--}" "${secs:--}" "${trace}" >> "${RESULTS}"
  echo "  ${pass} ${base} ${task}: ${status:-ERROR} rc=${rc}${frame:+, frame ${frame}}, ${secs:--}s, trace: ${trace%% *}"
}

echo "== pass base: committed engines (abc pdr/bmc3, aigsmt none) =="
cd "${HERE}"
for t in prove reach_valid reach_over neg_interval neg_seeded; do
  run_one base "${HERE}" p7_p8.sby "${t}" p7_p8.sby
done
for t in bmc prove neg_bound reach_nonzero neg_zeroize; do
  run_one base "${HERE}" p9.sby "${t}" p9.sby
done

echo "== pass aig: abc engines + aigsmt z3 (trace conversion) =="
for t in prove reach_valid reach_over neg_interval neg_seeded; do
  run_one aig "${OUT}" p7_p8.aig.sby "${t}" p7_p8.sby
done
for t in bmc prove neg_bound reach_nonzero neg_zeroize; do
  run_one aig "${OUT}" p9.aig.sby "${t}" p9.sby
done

echo "== pass smt: smtbmc z3 everywhere, 600 s per-task cap =="
for t in prove reach_valid reach_over neg_interval neg_seeded; do
  run_one smt "${OUT}" p7_p8.smt.sby "${t}" p7_p8.sby
done
for t in bmc prove neg_bound reach_nonzero neg_zeroize; do
  run_one smt "${OUT}" p9.smt.sby "${t}" p9.sby
done

echo "results: ${RESULTS}"
