# flow/common/core_flow.sh -- shared driver steps for the per-core
# verification/rtl/<core>/run.sh scripts. Source it; do not execute it.
#
# The caller sets HERE (its own directory) and NAME (the core directory name,
# also flow/build/<NAME>), parses its own options, then calls the steps below.
# Synthesis is a single corner (tt_025C_1v80), pre-P&R, cell area only.
#
# Every core ends on core_flow_finish, which owns the --sim-only split: CI asks
# each core for its own simulations and nothing else (scripts/ci-verify.sh), so
# neither synthesis nor the record verdict may run on that path.
#
# A core that has a gate-level mode (issue #179) also sets GATE_LEVEL=1 from its
# own --gate-level option and names its gate-level testcases in GATE_TESTCASES;
# core_flow_finish then runs them between synthesis and the verdict, because the
# netlist they simulate is the one synthesis just produced. A core that never
# sets GATE_LEVEL is unaffected -- it defaults to 0 everywhere it is read.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${REPO_ROOT}/flow/build/${NAME}"
PDK_ROOT="${PDK_ROOT:-${HOME}/.ciel}"

# The sky130_fd_sc_hd behavioural cell models a gate-level run elaborates ahead
# of the netlist, and the delay model it selects. Both come from the PDK install
# whose open_pdks revision scripts/setup-env.sh pins and record_lib.check_pdk()
# re-checks before any record is written, so they are not vendored here.
CELL_MODEL_DIR="${PDK_ROOT}/sky130A/libs.ref/sky130_fd_sc_hd/verilog"

_json_line() {  # _json_line <file> <python print expression over d>
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print('"$2"')' "$1"
}

core_flow_setup() {
  if [ ! -x "${REPO_ROOT}/.venv/bin/klt" ]; then
    echo "error: ${REPO_ROOT}/.venv is not provisioned." >&2
    echo "  -> run ./scripts/setup-env.sh first." >&2
    exit 1
  fi
  # The venv's bin/ must lead $PATH so klt runs the pinned yosys, not a host one.
  export PATH="${REPO_ROOT}/.venv/bin:${PATH}"
  mkdir -p "${OUT}"
  cd "${HERE}"
}

# core_flow_negctl_one <request> <json name> <result label> <grep pattern> \
#                      <what the bench wrongly passed> [evidence file]
#
# Runs one corrupted build and demands TWO things of it: `klt` must exit
# non-zero, AND <grep pattern> must match in <evidence file> -- the bench's own
# report of the failure it caught. A non-zero `klt` exit on its own is not
# evidence: a build that never elaborated (a missing source, a renamed define,
# a malformed request) exits non-zero too, and a negative control that "passes"
# for that reason has tested nothing (issue #151). The evidence file is removed
# before the run, so a stale report left behind by an earlier control -- `klt`
# does not clear this directory when a build fails -- cannot stand in for this
# control's own.
#
# <evidence file> defaults to the cocotb results XML, which carries the failing
# assertion text: the aes, sha256, hmac and keyladder benches give that text a
# distinctive prefix ("first failing vector: ...") and match on it. The drbg and
# trng_if benches assert with an unprefixed message, so they pass the cocotb log
# instead and match their own "SUMMARY ... failures=<n>" line with a non-zero n.
#
# Does not exit 0 itself: the caller may chain several controls. Chaining stops
# at the first control the bench fails to catch (exit 1) rather than running the
# rest -- one uncaught fault already fails the run, and stopping leaves that
# control as the last thing printed. Every caller chains on this helper.
core_flow_negctl_one() {
  local evidence="${6:-.klt/functional-verification/results_icarus.xml}"
  local caught
  rm -f "${evidence}"
  if klt functional-verification "${1}" --format json > "${OUT}/${2}"; then
    echo "FAIL: the bench passed with ${5}" >&2
    exit 1
  fi
  caught="$(grep -o "${4}" "${evidence}" 2>/dev/null | head -1 || true)"
  if [ -z "${caught}" ]; then
    echo "FAIL: ${5}: klt exited non-zero but ${evidence} reports no caught" \
         "failure -- the build, not the bench, may have failed" >&2
    exit 1
  fi
  _json_line "${OUT}/${2}" '"'"${3}"'", d["status"], "(expected fail)"'
  echo "${caught}"
}

# core_flow_negctl <what is corrupted> <noun> -- exit 0 only if the bench catches it.
core_flow_negctl() {
  echo "== negative control: ${1}; the bench must fail =="
  core_flow_negctl_one sim-negctl-request.json negctl.json "negative control:" \
    'first failing vector: [^&]*' "a corrupted ${2}"
  exit 0
}

core_flow_sim() {
  echo "== RTL simulation (klt functional-verification: cocotb + Icarus) =="
  klt functional-verification sim-request.json --format json > "${OUT}/sim.json"
  _json_line "${OUT}/sim.json" 'd["status"], d["passed_count"], "/", d["test_count"], "tests"'
  grep -o 'SUMMARY[^<]*' .klt/functional-verification/test_icarus.log | head -1 || true
}

# core_flow_check_opts <SIM_ONLY 0|1> <RECORD 0|1> [GATE_LEVEL 0|1] -- reject the
# option pairs that cannot mean anything, before a bench runs rather than after:
# a record is a simulation AND synthesis result, and --sim-only never
# synthesizes; for the same reason --sim-only cannot produce the netlist
# --gate-level simulates. Both are rejected here rather than failing later on a
# missing synth.json, which would read as a flow bug rather than a usage error.
core_flow_check_opts() {
  if [ "${1}" = 1 ] && [ "${2}" = 1 ]; then
    echo "error: --sim-only and --record are mutually exclusive:" >&2
    echo "  --sim-only stops before synthesis, and a record reports one." >&2
    exit 2
  fi
  if [ "${1}" = 1 ] && [ "${3:-0}" = 1 ]; then
    echo "error: --sim-only and --gate-level are mutually exclusive:" >&2
    echo "  --sim-only stops before synthesis, and --gate-level simulates the" >&2
    echo "  netlist synthesis produces. Drop --sim-only to run the gate-level" >&2
    echo "  mode; it is deliberately not on CI's path." >&2
    exit 2
  fi
}

# core_flow_synth [what] -- the optional name goes in the banner ("synthesis of <what>").
core_flow_synth() {
  echo "== synthesis${1:+ of ${1}} (klt synthesize -> sky130_fd_sc_hd, tt_025C_1v80) =="
  klt synthesize synth-request.json --pdk sky130A --pdk-root "${PDK_ROOT}" \
    --format json > "${OUT}/synth.json"
  _json_line "${OUT}/synth.json" 'd["status"], d["instance_count"], "instances", d["area_um2"], "um2"'
}

# The gate-level request renderer. `request.sources` is static JSON but the
# netlist path is not: `klt synthesize` writes into a freshly-claimed per-run
# directory (.klt/synthesize/run-<uuid>/), so the only honest source for the
# path is the report that run just wrote. This reads it from <synth json>,
# substitutes it into <template> along with the two cell-model paths, the bench
# directory and the testcase, and validates the result as JSON.
#
# It refuses rather than renders in three cases, each of which would otherwise
# produce a gate-level PASS that means nothing:
#   - the synthesis status is not `ok` (there is no netlist to believe);
#   - the netlist on disk does not hash to the `netlist_sha256` the report
#     records, i.e. a stale netlist from an earlier run in a dirty
#     flow/build/<core>/ (so AC4's netlist hash is a *verified* read, not an
#     assumption, and a re-run cannot silently simulate yesterday's gates);
#   - a placeholder survived substitution, or a source does not exist.
_GATE_RENDER_PY='
import hashlib, json, os, re, sys
tpl, synth, out, testcase, bench_dir, models, repo = sys.argv[1:8]
d = json.load(open(synth))
if d.get("status") != "ok":
    raise SystemExit(f"gate-level: {synth} reports status {d.get('status')!r}, "
                     "not ok -- refusing to simulate its netlist")
nl = d["netlist_path"]
nl = nl["path"] if isinstance(nl, dict) else nl
nl = nl if os.path.isabs(nl) else os.path.join(repo, nl)
want = str(d["netlist_sha256"]).split(":")[-1]
got = hashlib.sha256(open(nl, "rb").read()).hexdigest()
if got != want:
    raise SystemExit(f"gate-level: {nl}\n  hashes   {got}\n  but {synth} records "
                     f"{want}\n  -- a stale netlist, not this run\x27s; refusing")
text = open(tpl).read()
for key, val in (("@PRIMITIVES@", os.path.join(models, "primitives.v")),
                 ("@CELL_LIB@", os.path.join(models, "sky130_fd_sc_hd.v")),
                 ("@NETLIST@", nl), ("@BENCH_DIR@", bench_dir),
                 ("@TESTCASE@", testcase)):
    text = text.replace(key, val)
left = re.findall(r"@[A-Z_]+@", text)
if left:
    raise SystemExit(f"gate-level: {tpl} has unsubstituted placeholder(s) {left}")
req = json.loads(text)
# The template documents itself in "_comment"; the rendered request is handed
# to klt with the same key set as every other request in the repo.
req = {k: v for k, v in req.items() if not k.startswith("_")}
missing = [p for p in req["sources"] if not os.path.isfile(p)]
if missing:
    raise SystemExit(f"gate-level: request source(s) do not exist: {missing}")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w") as fh:
    json.dump(req, fh, indent=2)
print(f"netlist {os.path.relpath(nl, repo)} sha256:{got[:16]}... (verified)")
'

# core_flow_gate_render <template> <synth json> <out request> <testcase>
core_flow_gate_render() {
  python3 -c "${_GATE_RENDER_PY}" "${1}" "${2}" "${3}" "${4}" \
    "${HERE}" "${CELL_MODEL_DIR}" "${REPO_ROOT}"
}

# AC5 of issue #179, as a gate rather than a promise. The acceptance criterion
# is that every testbench check reading an internal RTL signal name either runs
# at gate level or is named in the record as not run there. The bench reads
# those names hierarchically (dut.state_q, getattr(dut, "hh")), which raises in
# cocotb if the name did not survive synthesis -- so a testcase that RUNS is its
# own proof that its names resolved in the netlist, and the only way to leave
# the criterion unmet is to leave a testcase out silently.
#
# So that is what is checked: every @cocotb.test() in the bench module must be
# either in GATE_TESTCASES or declared in GATE_EXCLUDED as "<name>=<reason>".
# Adding a testcase to a bench then fails the gate-level run until someone
# decides which it is, and the reason reaches the record instead of a gap.
_GATE_COVERAGE_PY='
import re, sys
bench, run_names, excluded = sys.argv[1:4]
found = set(re.findall(r"@cocotb\.test\(\)\s*\n\s*async def (\w+)", open(bench).read()))
run = set(run_names.split())
if not run:
    raise SystemExit("gate-level: GATE_TESTCASES is empty -- a gate-level run with "
                     "no testcase in it proves nothing about the netlist")
skip = {}
for entry in excluded.split("\n"):
    entry = entry.strip()
    if not entry:
        continue
    if "=" not in entry:
        raise SystemExit(f"gate-level: GATE_EXCLUDED entry {entry!r} is not <name>=<reason>")
    name, _, reason = entry.partition("=")
    skip[name.strip()] = reason.strip()
    if not skip[name.strip()]:
        raise SystemExit(f"gate-level: GATE_EXCLUDED names {name!r} with no reason")
unknown = (run | set(skip)) - found
if unknown:
    raise SystemExit(f"gate-level: {bench} has no testcase(s) {sorted(unknown)}")
both = run & set(skip)
if both:
    raise SystemExit(f"gate-level: testcase(s) {sorted(both)} are both run and excluded")
missing = found - run - set(skip)
if missing:
    raise SystemExit(
        f"gate-level: testcase(s) {sorted(missing)} in {bench} are neither in\n"
        "  GATE_TESTCASES nor declared in GATE_EXCLUDED as <name>=<reason>.\n"
        "  Issue #179 AC5: a check that reads an internal RTL signal name must\n"
        "  either run at gate level or be named in the record as not run there,\n"
        "  so a new testcase cannot default into neither.")
print("gate-level testcase coverage: run " + " ".join(sorted(run)) +
      ("; not run at gate level " + ", ".join(f"{k} ({v})" for k, v in sorted(skip.items()))
       if skip else "; none excluded"))
'

# core_flow_gate -- the gate-level positive runs, one per GATE_TESTCASES entry.
#
# Each testcase gets its own directory under ${OUT}: the rendered request lands
# there, so klt's own .klt/functional-verification/ scratch lands beside it and
# one testcase's log cannot stand in for another's -- nor overwrite the RTL
# run's log under verification/rtl/<core>/, which record_lib reads the SUMMARY
# line out of. Writes ${OUT}/gate.json, which make_record.py reads: its absence
# is what makes a non---gate-level record say no gate-level simulation was run.
core_flow_gate() {
  local tc req
  if [ -z "${GATE_TESTCASES:-}" ]; then
    echo "error: GATE_LEVEL=1 but GATE_TESTCASES names no testcase." >&2
    echo "  A core's run.sh sets both: which testcases run at gate level, and" >&2
    echo "  (in GATE_EXCLUDED, as <name>=<reason>) which do not and why." >&2
    exit 2
  fi
  echo "== gate-level simulation (same bench, sky130_fd_sc_hd netlist, FUNCTIONAL + UNIT_DELAY #1, no SDF) =="
  python3 -c "${_GATE_COVERAGE_PY}" \
    "${HERE}/$(_json_line "${HERE}/sim-request.json" 'd["testbench"]["module"]').py" \
    "${GATE_TESTCASES}" "${GATE_EXCLUDED:-}"
  : > "${OUT}/gate-testcases.txt"
  for tc in ${GATE_TESTCASES}; do
    req="${OUT}/gate-${tc}/request.json"
    core_flow_gate_render "${HERE}/sim-gate-request.json.in" "${OUT}/synth.json" \
      "${req}" "${tc}"
    klt functional-verification "${req}" --format json > "${OUT}/gate-${tc}.json"
    _json_line "${OUT}/gate-${tc}.json" \
      '"'"gate ${tc}:"'", d["status"], d["passed_count"], "/", d["test_count"], "tests"'
    echo "${tc}" >> "${OUT}/gate-testcases.txt"
  done
  python3 -c '
import json, sys
out, synth, excluded = sys.argv[1:4]
names = [n for n in open(f"{out}/gate-testcases.txt").read().split() if n]
runs = {n: json.load(open(f"{out}/gate-{n}.json")) for n in names}
skip = dict(e.strip().split("=", 1) for e in excluded.split("\n") if e.strip())
d = json.load(open(synth))
nl = d["netlist_path"]
req = json.load(open(f"{out}/gate-{names[0]}/request.json"))
json.dump({"netlist_path": nl["path"] if isinstance(nl, dict) else nl,
           "netlist_sha256": d["netlist_sha256"],
           "instance_count": d["instance_count"],
           "cell_models": [s for s in req["sources"][:-1]],
           "defines": req["options"]["defines"],
           "sdf": req["options"].get("sdf"),
           "status": "pass" if all(r["status"] == "pass" for r in runs.values()) else "fail",
           "testcases": runs,
           "excluded": {k.strip(): v.strip() for k, v in skip.items()}},
          open(f"{out}/gate.json", "w"), indent=2)
' "${OUT}" "${OUT}/synth.json" "${GATE_EXCLUDED:-}"
}

# core_flow_gate_negctl <define> <testcase> <what is corrupted> <noun>
#
# The gate-level negative control. The corruption is a `ifdef in the RTL, so it
# has to be injected at SYNTHESIS -- the netlist is the simulation source and
# carries no preprocessor. The klt the repo pins has no way to pass a define to
# `klt synthesize`: its request has no `defines` key (2AMLogic/klayout-tools
# #4196, already filed and closed COMPLETED upstream -- later klt has the key,
# so this is a consequence of the KLT_VERSION pin, and a pin bump retires this
# wrapper). So the define is applied the one way the Verilog preprocessor itself
# offers: a generated wrapper that defines the macro and `include`s the RTL,
# used as that synthesis run's only source.
#
# Then the ordinary core_flow_negctl_one does the judging, unchanged: `klt` must
# exit non-zero AND the bench must name the vector it caught (#151). Note the
# simulation request needs no define -- the fault is baked into the gates.
core_flow_gate_negctl() {
  echo "== gate-level negative control: ${3}, synthesized; the bench must fail =="
  # One step, so the wrapper and the request that reads it cannot disagree: the
  # wrapper `include`s exactly the sources the positive synth-request.json
  # names, in order, and becomes that request's only source. Every other field
  # -- hdl_toplevel, pdk, corner, constraints -- is copied, so the control
  # differs from the positive build in the define and nothing else.
  python3 -c '
import json, os, sys
tpl, define, src, out = sys.argv[1:5]
req = json.load(open(tpl))
here = os.path.dirname(os.path.abspath(tpl))
rtl = [s if os.path.isabs(s) else os.path.realpath(os.path.join(here, s))
       for s in req["sources"]]
missing = [p for p in rtl if not os.path.isfile(p)]
if missing:
    raise SystemExit(f"gate-level negative control: source(s) not found: {missing}")
os.makedirs(os.path.dirname(src), exist_ok=True)
with open(src, "w") as fh:
    fh.write(f"// generated by core_flow_gate_negctl -- `{define}` applied to the\n"
             "// RTL below at synthesis, the one way the Verilog preprocessor offers\n"
             "// (the pinned klt synthesize request has no defines field).\n")
    fh.write(f"`define {define}\n")
    for path in rtl:
        fh.write(f"`include \"{path}\"\n")
req["sources"] = [src]
with open(out, "w") as fh:
    json.dump(req, fh, indent=2)
' "${HERE}/synth-request.json" "${1}" "${OUT}/gate-negctl/${NAME}_negctl.v" \
  "${OUT}/gate-negctl/synth-request.json"
  klt synthesize "${OUT}/gate-negctl/synth-request.json" --pdk sky130A \
    --pdk-root "${PDK_ROOT}" --format json > "${OUT}/gate-negctl-synth.json"
  _json_line "${OUT}/gate-negctl-synth.json" \
    '"gate negctl synthesis:", d["status"], d["instance_count"], "instances"'
  core_flow_gate_render "${HERE}/sim-gate-request.json.in" \
    "${OUT}/gate-negctl-synth.json" "${OUT}/gate-negctl/request.json" "${2}"
  core_flow_negctl_one "${OUT}/gate-negctl/request.json" gate-negctl.json \
    "gate-level negative control:" 'first failing vector: [^&]*' \
    "a corrupted ${4} in the netlist" \
    "${OUT}/gate-negctl/.klt/functional-verification/results_icarus.xml"
  exit 0
}

# core_flow_verdict <RECORD 0|1> -- verdict, plus a record when RECORD=1.
core_flow_verdict() {
  if [ "${1}" = 1 ]; then
    python3 "${HERE}/make_record.py" --out-dir "${OUT}" --pdk-root "${PDK_ROOT}"
  else
    python3 "${HERE}/make_record.py" --out-dir "${OUT}" --pdk-root "${PDK_ROOT}" --check-only
  fi
}

# core_flow_finish <SIM_ONLY 0|1> <RECORD 0|1> [what] -- the tail every core
# shares. SIM_ONLY=1 stops here: that is the whole of CI's positive run, which
# has no PDK and mints no evidence. Otherwise synthesize, then settle the
# verdict (and write a record when RECORD=1).
#
# GATE_LEVEL=1 (a caller-set variable, not a positional, so the four cores with
# no gate-level mode keep calling this unchanged) inserts the gate-level runs
# between the two: they simulate the netlist synthesis just wrote, and the
# verdict has to see their result. ${OUT}/gate.json is removed first, so a
# record can never pick up a previous run's gate result -- the same reason the
# sha256 flow removes million.json before deciding whether to write it.
core_flow_finish() {
  if [ "${1}" = 1 ]; then
    echo "== --sim-only: stopping before synthesis; no verdict, no record =="
    return 0
  fi
  rm -f "${OUT}/gate.json"
  core_flow_synth "${3:-}"
  if [ "${GATE_LEVEL:-0}" = 1 ]; then
    core_flow_gate
  fi
  core_flow_verdict "${2}"
}
