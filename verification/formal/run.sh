#!/usr/bin/env bash
#
# verification/formal/run.sh -- run the SymbiYosys files for P-7, P-8 and P-9
# (spec/key-isolation-properties.md) on the RTL.
#
#   ./scripts/setup-env.sh                    # once: .venv (provides yowasp-sby)
#   ./verification/formal/run.sh              # all tasks, summary table
#   ./verification/formal/run.sh --record     # same, then write a record under
#                                             # verification/records/drbg-trng-formal/records/
#
# Each .sby file has proof/bounded tasks (must PASS) and tasks that must FAIL:
# reach_* are vacuity checks (the assertion "this never happens" is violated, so
# the thing the property talks about is reachable), neg_* are the RTL with a
# deliberate defect or a claim one cycle too early. A task counts as OK when
# sby exits 0 (a task marked `expect fail` that fails is exit 0). Exit 0 only
# if every task is OK.
#
# Engines: only the Yosys-internal ones are provisioned (`abc pdr` for unbounded
# proofs, `abc bmc3` for bounded checks). The venv's sby has no SMT solver, so
# smtbmc engines and counterexample trace conversion (`aigsmt`) are not used;
# failing tasks therefore produce no waveform. Tool gap filed generically on
# 2AMLogic/klayout-tools (see the record).
#
# `abc` engines run a separate `yosys-abc`, which the YoWASP wheel does not ship:
# a native Yosys install must provide it (CI: apt `yosys`); checked up front.
#
# yowasp-sby looks for `yosys-witness` / `yosys-smtbmc` by those names; the
# venv ships them as yowasp-yosys-*, so a shim directory under flow/build/
# links them (no host tool is touched).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
OUT="${REPO_ROOT}/flow/build/formal"
SHIM="${REPO_ROOT}/flow/build/formal-bin"

RECORD=0
for arg in "$@"; do
  case "${arg}" in
    --record) RECORD=1 ;;
    *) echo "unknown option: ${arg}" >&2; exit 2 ;;
  esac
done

SBY="${REPO_ROOT}/.venv/bin/yowasp-sby"
if [ ! -x "${SBY}" ]; then
  SBY="$(command -v sby || true)"
fi
if [ -z "${SBY}" ] || [ ! -x "${SBY}" ]; then
  echo "error: no SymbiYosys found (looked for ${REPO_ROOT}/.venv/bin/yowasp-sby and sby on PATH)." >&2
  echo "  -> run ./scripts/setup-env.sh first. The properties are NOT deferred; this run proved nothing." >&2
  exit 2
fi
if ! command -v yosys-abc > /dev/null 2>&1; then
  echo "error: yosys-abc not found on PATH. sby's 'abc bmc3'/'abc pdr' engines run it as a" >&2
  echo "  separate program; the pinned yowasp-yosys wheel does not ship one." >&2
  echo "  -> install a native Yosys (it provides yosys-abc), e.g. 'apt-get install yosys'." >&2
  echo "  Without it every task exits 16 and the reach_*/neg_* controls cannot be told from a missing tool." >&2
  exit 2
fi
mkdir -p "${OUT}" "${SHIM}"
for t in witness smtbmc; do
  ln -sf "${REPO_ROOT}/.venv/bin/yowasp-yosys-${t}" "${SHIM}/yosys-${t}"
done
export PATH="${SHIM}:${REPO_ROOT}/.venv/bin:${PATH}"

: > "${OUT}/results.tsv"
bad=0
cd "${HERE}"
run_task() { # run_task <file.sby> <task>
  local file="$1" task="$2" dir="${OUT}/${1%.sby}_${2}" rc=0
  rm -rf "${dir}"
  "${SBY}" -f -d "${dir}" "${file}" "${task}" > "${OUT}/${file%.sby}_${task}.out" 2>&1 || rc=$?
  local status engine frame secs
  # logfile.txt is missing when sby dies early; every grep tolerates that so
  # the FAIL branch below (and the sby output it prints) is always reached.
  status="$(grep -o 'DONE ([A-Z]*' "${dir}/logfile.txt" 2>/dev/null | tail -1 | sed 's/DONE (//' || true)"
  engine="$(grep -o 'summary: engine_0 ([a-z0-9 ]*) returned [A-Z]*' "${dir}/logfile.txt" 2>/dev/null | tail -1 | sed 's/summary: //' || true)"
  frame="$(grep -o 'asserted in frame [0-9]*' "${dir}/logfile.txt" 2>/dev/null | head -1 | grep -o '[0-9]*$' || true)"
  secs="$(grep -o 'Elapsed clock time.*(\([0-9]*\))' "${dir}/logfile.txt" 2>/dev/null | tail -1 | grep -o '([0-9]*)' | tr -d '()' || true)"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "${file}" "${task}" "${status:-ERROR}" "${rc}" "${engine:-none}" "${frame:--}" "${secs:--}" >> "${OUT}/results.tsv"
  if [ "${rc}" = 0 ]; then
    echo "  ok    ${file} ${task}: ${status} (${engine}${frame:+, counterexample at frame ${frame}}, ${secs}s)"
  else
    echo "  FAIL  ${file} ${task}: sby exit ${rc}, see ${OUT}/${file%.sby}_${task}.out" >&2
    tail -n 40 "${OUT}/${file%.sby}_${task}.out" | sed 's/^/        | /' >&2 || true
    bad=1
  fi
}

echo "== P-7 / P-8: rtl/drbg/ctr_drbg.v =="
for t in prove reach_valid reach_over neg_interval neg_seeded; do run_task p7_p8.sby "${t}"; done
echo "== P-9: rtl/trng_if/trng_if.v + rtl/drbg/ctr_drbg.v =="
for t in bmc prove neg_bound reach_nonzero neg_zeroize; do run_task p9.sby "${t}"; done

if [ "${bad}" != 0 ]; then
  echo "formal: at least one task did not meet its expectation" >&2
  exit 1
fi
echo "formal: all tasks met their expectation"
if [ "${RECORD}" = 1 ]; then
  python3 "${HERE}/make_record.py" --out-dir "${OUT}"
fi
