#!/usr/bin/env bash
#
# verification/formal/run.sh -- run the SymbiYosys files for P-7, P-8 and P-9
# (spec/key-isolation-properties.md) on the RTL, and -- with --netlist -- on
# the klt-synthesized sky130_fd_sc_hd netlist of the same modules (issue #177).
#
#   ./scripts/setup-env.sh                    # once: .venv (provides yowasp-sby)
#   ./verification/formal/run.sh              # RTL tasks, summary table
#   ./verification/formal/run.sh --record     # same, then write a record under
#                                             # verification/records/drbg-trng-formal/records/
#   ./verification/formal/run.sh --netlist [--record]
#                                             # RTL tasks + the netlist re-proof:
#                                             # P-7/P-8/P-9 on klt synthesize netlists
#                                             # (klt, the sky130A liberty at
#                                             # tt_025C_1v80 via PDK_ROOT, iverilog;
#                                             # not part of the cold start, see
#                                             # scripts/cold-start-benches.sh)
#
# Each .sby file has proof/bounded tasks (must PASS) and tasks that must FAIL:
# reach_* are vacuity checks (the assertion "this never happens" is violated, so
# the thing the property talks about is reachable), neg_* are the RTL with a
# deliberate defect or a claim one cycle too early. A task counts as OK when
# sby exits 0 (a task marked `expect fail` that fails is exit 0). The verdict
# is not made here: after the last task this script asks make_record.py (its
# EXPECT table is the one copy of the expectation policy) to judge
# results.tsv -- on every run, --record or not (issue #207) -- and exits 0
# only if every task met its expectation.
#
# Engines: RTL tasks use only the Yosys-internal ones (`abc pdr` for unbounded
# proofs, `abc bmc3` for bounded checks). The venv's sby has no SMT solver, so
# smtbmc engines and counterexample trace conversion (`aigsmt`) are not used on
# the RTL tasks; failing RTL tasks therefore produce no waveform. Tool gap
# filed generically on 2AMLogic/klayout-tools (see the record).
#
# Netlist tasks (net_*.sby) use the RTL tasks' own Yosys-internal engines:
# `abc pdr` for the unbounded netlist proofs (verified to close on the
# liberty-mapped netlist; the record states the engine per row), `abc bmc3`
# for the bounded checks and the negative controls. A netlist proof that does
# not close within its depth or the 1500 s per-task cap is recorded as
# "reached depth N, not proven" (the run still exits 0 and the record is
# still written); a netlist negative control must actually FAIL with a
# counterexample.
#
# `abc` engines run a separate `yosys-abc`, which the YoWASP wheel does not ship:
# a native Yosys install must provide it (CI: apt `yosys`); checked up front.
#
# yowasp-sby looks for `yosys-witness` / `yosys-smtbmc` by those names; the
# venv ships them as yowasp-yosys-*, so a shim directory under flow/build/
# links them (no host tool is touched).
#
# Synthesis (netlist mode) goes through `klt synthesize` with the venv's pinned
# yowasp-yosys first on PATH. klt 0.8.0 kills yosys at a hard-coded 300 s, and
# yosys's abc pass deadlocks when the temp path is long (yosys-abc's readline
# wraps the echoed `source` line and the protocol never completes --
# 2AMLogic/klayout-tools#5780; the daemon's default TMPDIR is long enough to
# trip it), so the netlist section pins a short TMPDIR for every synthesis.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
OUT="${REPO_ROOT}/flow/build/formal"
SHIM="${REPO_ROOT}/flow/build/formal-bin"

RECORD=0
NETLIST=0
for arg in "$@"; do
  case "${arg}" in
    --record) RECORD=1 ;;
    --netlist) NETLIST=1 ;;
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
cd "${HERE}"
run_task() { # run_task <file.sby> <task>
  local file="$1" task="$2" base
  base="$(basename "${file}")"
  local dir="${OUT}/${base%.sby}_${2}" rc=0
  rm -rf "${dir}"
  "${SBY}" -f -d "${dir}" "${file}" "${task}" > "${OUT}/${base%.sby}_${task}.out" 2>&1 || rc=$?
  local status engine frame secs
  # logfile.txt is missing when sby dies early; every grep tolerates that so
  # the status line below (and the sby output it prints) is always reached.
  status="$(grep -o 'DONE ([A-Z]*' "${dir}/logfile.txt" 2>/dev/null | tail -1 | sed 's/DONE (//' || true)"
  engine="$(grep -o 'summary: engine_0 ([a-z0-9 ]*) returned [A-Z]*' "${dir}/logfile.txt" 2>/dev/null | tail -1 | sed 's/summary: //' || true)"
  frame="$(grep -o 'asserted in frame [0-9]*' "${dir}/logfile.txt" 2>/dev/null | head -1 | grep -o '[0-9]*$' || true)"
  secs="$(grep -o 'Elapsed clock time.*(\([0-9]*\))' "${dir}/logfile.txt" 2>/dev/null | tail -1 | grep -o '([0-9]*)' | tr -d '()' || true)"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "${base}" "${task}" "${status:-ERROR}" "${rc}" "${engine:-none}" "${frame:--}" "${secs:--}" >> "${OUT}/results.tsv"
  # These lines report what sby did, not whether that met the task's
  # expectation: the verdict is make_record.py's, once, after the last task
  # (--check-only below), so this script keeps no copy of the policy
  # (issue #207). When sby did not exit cleanly, dump the tail of its output
  # for diagnosis, whatever the task's expectation is -- a netlist proof that
  # stopped at its depth/time cap also lands here and is judged reached-depth
  # by make_record.py, not by these lines.
  if [ "${rc}" = 0 ]; then
    echo "  ok    ${base} ${task}: ${status} (${engine}${frame:+, counterexample at frame ${frame}}, ${secs}s)"
  else
    echo "  rc=${rc}   ${base} ${task}: ${status} (${engine}${frame:+, counterexample at frame ${frame}}, ${secs}s), see ${OUT}/${base%.sby}_${task}.out" >&2
    tail -n 40 "${OUT}/${base%.sby}_${task}.out" | sed 's/^/        | /' >&2 || true
  fi
}

echo "== P-7 / P-8: rtl/drbg/ctr_drbg.v =="
for t in prove reach_valid reach_over neg_interval neg_seeded; do run_task p7_p8.sby "${t}"; done
echo "== P-9: rtl/trng_if/trng_if.v + rtl/drbg/ctr_drbg.v =="
for t in bmc prove neg_bound reach_nonzero neg_zeroize; do run_task p9.sby "${t}"; done

if [ "${NETLIST}" = 1 ]; then
  # ---- netlist re-proof (issue #177) -------------------------------------
  echo "== netlist re-proof: klt synthesize + the RTL tasks' own abc engines =="
  for tool in klt yosys yosys-smtbmc z3; do
    if [ ! -x "${REPO_ROOT}/.venv/bin/${tool}" ]; then
      echo "error: ${REPO_ROOT}/.venv/bin/${tool} missing; run ./scripts/setup-env.sh first." >&2
      exit 1
    fi
  done
  command -v iverilog >/dev/null || { echo "error: iverilog not on PATH (the op_q binding probe simulates the flattened netlist with it)" >&2; exit 1; }
  PDK_ROOT="${PDK_ROOT:-${HOME}/.ciel}"
  LIB="${PDK_ROOT}/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
  [ -f "${LIB}" ] || { echo "error: liberty ${LIB} not found (PDK_ROOT); the netlist tasks need the sky130A PDK" >&2; exit 1; }
  # The venv's bin/ must lead $PATH so the pinned yosys, sby, z3 and klt run,
  # not host ones (the same rule as verification/formal/keyladder/run.sh).
  export PATH="${REPO_ROOT}/.venv/bin:${PATH}"
  # klayout-tools#5780: yosys's abc pass deadlocks when the temp path is long
  # (yosys-abc's readline wraps the echoed `source' line). The ambient TMPDIR
  # can be long enough to trip it, so every synthesis below runs with a short one.
  NET_TMP="$(mktemp -d /tmp/kltformXXXXXX)"
  export TMPDIR="${NET_TMP}"
  # Remove the pinned short temp dir on the way out, error paths included
  # (issue #207; set -euo pipefail makes the EXIT trap cover them).
  trap 'rm -rf "${NET_TMP}"' EXIT
  STAGE="${OUT}/netlist"
  rm -rf "${STAGE}"
  mkdir -p "${STAGE}"
  cp "${LIB}" "${STAGE}/sky130_fd_sc_hd.lib"

  # 1. mutant RTL sources + the op_q probe bench (iverilog -E; klt synthesize
  #    takes no defines and no parameter overrides, so the mutants are
  #    source-mutated copies -- 2AMLogic/klayout-tools#4196/#4698).
  python3 "${HERE}/gen_netlist.py" --stage "${STAGE}" --prepare --lib "${LIB}"

  # 2. six syntheses: clean + interval-1 + three mutants (ctr_drbg), trng_if.
  synth() {  # synth NAME TOPLEVEL SOURCE
    local name="$1" top="$2" src="$3"
    local work="${STAGE}/synth_${name}"
    mkdir -p "${work}"
    python3 - "${work}" "${top}" "${src}" <<'PY'
import json, os, sys
work, top, src = sys.argv[1], sys.argv[2], sys.argv[3]
json.dump({"schema": "klt.synthesize.request/1", "engine": "yosys",
           "sources": [os.path.relpath(src, work)], "hdl_toplevel": top,
           "pdk": {"cell_library": "sky130_fd_sc_hd", "corner": "tt_025C_1v80"},
           "constraints": {"clock_period_ns": None}},
          open(os.path.join(work, "synth-request.json"), "w"), indent=2)
PY
    (cd "${work}" && klt synthesize synth-request.json --pdk sky130A --pdk-root "${PDK_ROOT}" \
        --format json > synth.json)
    local rid
    rid="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "${work}/synth.json")"
    cp "${work}/.klt/synthesize/${rid}/${top}_synth.v" "${STAGE}/net_${name}.v"
    echo "  synth ${name}: run ${rid}"
  }
  echo "-- synthesis (klt synthesize, tt_025C_1v80): clean + interval-1 + three mutants + trng_if --"
  synth clean      ctr_drbg "${STAGE}/rtl_clean.v"
  synth interval   ctr_drbg "${STAGE}/rtl_interval.v"
  synth neg_interval ctr_drbg "${STAGE}/rtl_neg_interval.v"
  synth neg_seeded ctr_drbg "${STAGE}/rtl_neg_seeded.v"
  synth neg_zeroize ctr_drbg "${STAGE}/rtl_neg_zeroize.v"
  synth if_clean   trng_if  "${REPO_ROOT}/rtl/trng_if/trng_if.v"

  # 3. splice the property text onto each netlist module (registers, literal
  #    encodings and the op_q binding are derived and machine-checked there).
  python3 "${HERE}/gen_netlist.py" --stage "${STAGE}" --lib "${LIB}" \
    --netlist clean="${STAGE}/net_clean.v" \
    --netlist interval="${STAGE}/net_interval.v" \
    --netlist neg_interval="${STAGE}/net_neg_interval.v" \
    --netlist neg_seeded="${STAGE}/net_neg_seeded.v" \
    --netlist neg_zeroize="${STAGE}/net_neg_zeroize.v" \
    --netlist if_clean="${STAGE}/net_if_clean.v"

  # 4. netlist SymbiYosys tasks. NET_PROVE_DEPTH exists so the reached-depth
  #    recording can be exercised at a truncated depth; the default is the
  #    depth the RTL proofs ran at. sby resolves the [files] list against its
  #    working directory, so the tasks run from the stage.
  cp "${HERE}/net_p7_p8.sby" "${HERE}/net_p9.sby" "${STAGE}/"
  sed -i "s#@NET_PROVE_DEPTH@#${NET_PROVE_DEPTH:-20}#" "${STAGE}/net_p7_p8.sby" "${STAGE}/net_p9.sby"
  cd "${STAGE}"
  echo "== P-7 / P-8 on the synthesized netlist =="
  for t in net_prove net_reach_valid net_reach_over net_neg_interval net_neg_seeded; do
    run_task net_p7_p8.sby "${t}"
  done
  echo "== P-9 on the synthesized netlists =="
  for t in net_bmc net_prove net_neg_bound net_reach_nonzero net_neg_zeroize; do
    run_task net_p9.sby "${t}"
  done
fi

# One judge for every run, --record or not (issue #207): make_record.py's
# EXPECT table is the only copy of the expectation policy, and --check-only
# returns right after that verdict, before any recording work. A negative
# control that timed out or came back UNKNOWN therefore fails the script
# here -- in exactly the mode (--netlist without --record) it used to slip
# through as "not proven" with exit 0.
if ! python3 "${HERE}/make_record.py" --out-dir "${OUT}" --check-only; then
  echo "formal: at least one task did not meet its expectation" >&2
  exit 1
fi
echo "formal: all tasks met their expectation"
if [ "${RECORD}" = 1 ]; then
  python3 "${HERE}/make_record.py" --out-dir "${OUT}"
fi
