# flow/common/core_flow.sh -- shared driver steps for the per-core
# verification/rtl/<core>/run.sh scripts. Source it; do not execute it.
#
# The caller sets HERE (its own directory) and NAME (the core directory name,
# also flow/build/<NAME>), parses its options with core_flow_parse_opts below
# (the common flags plus whatever the core declares), then calls the steps.
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

# The negative-control evidence for the benches whose assertion messages carry
# no distinctive prefix (drbg, trng_if -- see core_flow_negctl_one): the bench's
# own "SUMMARY ... failures=<n>" line with a non-zero n, matched in the cocotb
# log. One definition here instead of a copy per core; the same log is what
# core_flow_summaries reads.
BENCH_LOG=.klt/functional-verification/test_icarus.log
NEG_EVIDENCE='SUMMARY.*failures=[1-9][0-9]*'

# core_flow_parse_opts "$@" -- the one option parser, instead of a copy per
# core. Recognizes the common three flags (--record, --negative-control,
# --sim-only -> RECORD, NEG, SIM_ONLY) and calls core_flow_check_opts itself,
# so a core cannot forget that pair check (trng_if once did). A core keeps only
# what is genuinely its own, declared before the call:
#   CORE_FLOW_EXTRA_OPTS    "<flag>:<VAR>" pairs; passing <flag> sets <VAR> to
#                           1 (sha256: --million-a:MILLION; trng_if:
#                           --skip-real:SKIP_REAL). The core initializes the
#                           variable itself and may read it with the opposite
#                           sense (SKIP_REAL defaults 0).
#   CORE_FLOW_UNSUPPORTED   a flag the driver knows but this core does not
#                           (trng_if: --sim-only, which stops before a
#                           synthesis this core never runs). Passing one is
#                           rejected by name, before the case below can claim
#                           it as a common flag.
# Unknown options keep the original message and exit status.
core_flow_parse_opts() {
  RECORD=0; NEG=0; SIM_ONLY=0
  local arg pair
  for arg in "$@"; do
    case " ${CORE_FLOW_UNSUPPORTED:-} " in
      *" ${arg} "*)
        echo "unsupported option: ${arg}" >&2
        exit 2 ;;
    esac
    case "${arg}" in
      --record) RECORD=1 ;;
      --negative-control) NEG=1 ;;
      --sim-only) SIM_ONLY=1 ;;
      *)
        for pair in ${CORE_FLOW_EXTRA_OPTS:-}; do
          if [ "${arg}" = "${pair%%:*}" ]; then
            printf -v "${pair#*:}" '1'
            continue 2
          fi
        done
        echo "unknown option: ${arg}" >&2
        exit 2 ;;
    esac
  done
  core_flow_check_opts "${SIM_ONLY}" "${RECORD}" "${GATE_LEVEL:-0}"
}
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

# core_flow_negctl_request <base request> <define> -- the base request document
# with <define> added to options.defines (value null, as `-D<define>` would),
# on stdout. An empty <define> yields the base document unchanged.
#
# This is what makes a negative control a control. A control is only evidence
# if it runs the SAME bench on the SAME sources as the positive run with
# exactly one fault injected, and until issue #161 that held only by hand: each
# control had its own tracked copy of the positive request, so a source added
# to sim-request.json and not to its copies left a control that failed for an
# unrelated reason (a missing module) and was still counted as "caught".
# Deriving the control from the positive request makes "same bench, one fault"
# true by construction. verification/rtl/trng_if/mk_req.py reached the same
# conclusion from the other direction (issue #136).
core_flow_negctl_request() {
  python3 -I -c 'import json, sys
doc = json.load(open(sys.argv[1]))
if sys.argv[2]:
    doc.setdefault("options", {}).setdefault("defines", {})[sys.argv[2]] = None
json.dump(doc, sys.stdout, indent=2)' "${1}" "${2}"
}

# core_flow_negctl_one <base request> <define> <json name> <result label> \
#                      <grep pattern> <what the bench wrongly passed> \
#                      [evidence file]
#
# Derives <base request> + <define> (above) and feeds it to `klt` on stdin, so
# the corrupted request is never a file in the tree. Relative `sources` paths
# in a stdin request resolve against the working directory and `klt` writes its
# artifacts there too -- verified against the pinned klayout-tools 0.8.0 -- and
# core_flow_setup has already `cd`-ed to the bench's own directory, which is
# what the tracked request files resolved against. A caller that runs these
# steps from anywhere else must pass <base request> and <evidence file> to
# match. The derived document is also written to ${OUT} so a failing run can be
# read back; nothing reads it, and it is build scratch, not tracked evidence.
#
# An empty <define> runs <base request> unchanged: verification/rtl/trng_if
# generates its requests with the fault already in them (mk_req.py), so it
# needs the evidence discipline below without the derivation.
#
# Demands TWO things of the run: `klt` must exit
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
  local evidence="${7:-.klt/functional-verification/results_icarus.xml}"
  local request caught
  # Not `local request=$(...)`: that would discard the generator's exit status.
  if ! request="$(core_flow_negctl_request "${1}" "${2}")"; then
    echo "FAIL: could not derive ${1}${2:+ + ${2}} -- the control never ran" >&2
    exit 1
  fi
  printf '%s\n' "${request}" > "${OUT}/${3%.json}-request.json"
  rm -f "${evidence}"
  if printf '%s\n' "${request}" \
      | klt functional-verification - --format json > "${OUT}/${3}"; then
    echo "FAIL: the bench passed with ${6}" >&2
    exit 1
  fi
  caught="$(grep -o "${5}" "${evidence}" 2>/dev/null | head -1 || true)"
  if [ -z "${caught}" ]; then
    echo "FAIL: ${6}: klt exited non-zero but ${evidence} reports no caught" \
         "failure -- the build, not the bench, may have failed" >&2
    exit 1
  fi
  _json_line "${OUT}/${3}" '"'"${4}"'", d["status"], "(expected fail)"'
  echo "${caught}"
}

# core_flow_negctl <define> <what it corrupts> <noun> -- exit 0 only if the
# bench catches it. The one-control shape: sim-request.json plus <define>.
core_flow_negctl() {
  echo "== negative control: ${1} ${2}; the bench must fail =="
  core_flow_negctl_one sim-request.json "${1}" negctl.json "negative control:" \
    'first failing vector: [^&]*' "a corrupted ${3}"
  exit 0
}

# core_flow_status <sim json> -- the one-line "<status> <passed>/<total> tests"
# print after each simulation; drbg open-coded it per elaboration and trng_if
# wrapped it as status().
core_flow_status() {
  _json_line "$1" 'd["status"], d["passed_count"], "/", d["test_count"], "tests"'
}

# core_flow_summaries [--first] -- every "SUMMARY ..." line in the cocotb log
# (${BENCH_LOG}, above); --first keeps only the first, for a run that produces
# one elaboration per log.
core_flow_summaries() {
  if [ "${1:-}" = "--first" ]; then
    grep -o 'SUMMARY[^<]*' "${BENCH_LOG}" | head -1 || true
  else
    grep -o 'SUMMARY[^<]*' "${BENCH_LOG}" || true
  fi
}

core_flow_sim() {
  echo "== RTL simulation (klt functional-verification: cocotb + Icarus) =="
  klt functional-verification sim-request.json --format json > "${OUT}/sim.json"
  core_flow_status "${OUT}/sim.json"
  core_flow_summaries --first
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
  # klt anchors a stdin request's artifacts to the working directory (the
  # post-#175 helper shape -- see core_flow_negctl_one's header), so the control
  # runs from ${OUT}/gate-negctl: what klt writes and the helper's CWD-default
  # evidence path then name the same place, and the RTL run's log under
  # verification/rtl/<core>/ -- which record_lib reads the SUMMARY line out of
  # -- stays untouched. The rendered request's sources are absolute, so the cd
  # cannot re-anchor them.
  cd "${OUT}/gate-negctl"
  core_flow_negctl_one request.json "" gate-negctl.json \
    "gate-level negative control:" 'first failing vector: [^&]*' \
    "a corrupted ${4} in the netlist"
  exit 0
}

# core_flow_sta_request <synth response> <sta request template> <destination> --
# the committed sta-request.json plus the one thing a tracked file cannot
# carry: the netlist to time. `klt synthesize` writes its netlist into a
# per-run scratch directory, so the path is read from the synthesis response's
# netlist_path -- a `{path, scope}` envelope -- rather than hardcoded
# (verified on the pinned klayout-tools 0.8.0, schema_version 2). scope
# "repo" resolves against REPO_ROOT; anything else refuses rather than feed
# `klt sta` a path that was never resolved. The derived document is written
# to ${OUT}: build scratch like the negative-control request, not tracked
# evidence.
core_flow_sta_request() {
  python3 -I -c 'import json, sys
synth = json.load(open(sys.argv[1]))
np = synth["netlist_path"]
if isinstance(np, dict):
    if np.get("scope") != "repo" or not np.get("path"):
        sys.exit("sta: synthesis netlist_path is not repo-relative: " + json.dumps(np))
    netlist = sys.argv[4] + "/" + np["path"]
else:
    netlist = np
doc = json.load(open(sys.argv[2]))
doc["verilog"] = netlist
with open(sys.argv[3], "w") as f:
    json.dump(doc, f, indent=2)' \
    "${1}" "${2}" "${3}" "${REPO_ROOT}"
}

# core_flow_sta [what] -- pre-layout setup timing of the netlist this run
# synthesizes: `klt synthesize sta-synth-request.json` (corner
# ss_100C_1v60, 20 ns clock target -- the synthesis the timing number is
# honest for, distinct from core_flow_synth's tt run) then `klt sta` in
# DEF-free verilog mode on the committed sta-request.json plus that netlist.
# A negative slack is data, not a failure: `klt sta` exits non-zero only when
# the analysis could not run (bad request, unresolvable PDK, a missing clock
# constraint, an OpenROAD engine error), never on a timing miss, and set -e
# keeps that contract -- a completed analysis exits 0 however negative the
# number.
core_flow_sta() {
  echo "== synthesis for timing${1:+ of ${1}} (klt synthesize -> sky130_fd_sc_hd, ss_100C_1v60, 20 ns target) =="
  klt synthesize sta-synth-request.json --pdk sky130A --pdk-root "${PDK_ROOT}" \
    --format json > "${OUT}/sta-synth.json"
  _json_line "${OUT}/sta-synth.json" 'd["status"], d["instance_count"], "instances", d["area_um2"], "um2"'
  echo "== pre-layout setup timing (klt sta: verilog netlist, no parasitics) =="
  core_flow_sta_request "${OUT}/sta-synth.json" "${HERE}/sta-request.json" \
    "${OUT}/sta-request.json"
  # Run `klt sta` from the repo root, not from HERE: on hosts where openroad
  # is the provisioned container wrapper (2am infra install -- `docker run`
  # mounting $PWD, $TMPDIR and $PDK_ROOT and nothing else), the engine can
  # only open paths under the invocation's own working directory. From HERE
  # (verification/rtl/<core>/) the script, metrics and logs klt writes under
  # ${OUT}/.klt/sta/ are invisible to the container and the run dies with
  # STA-0340 "cannot open" on a script that exists and is readable (observed
  # on the dispatch host, 2026-11-15). The repo root encloses both that
  # directory and the synthesized netlist's .klt/synthesize scratch, so every
  # path the engine touches is inside the one mounted tree. The derived
  # request carries absolute paths, so nothing else depends on the CWD.
  ( cd "${REPO_ROOT}" && klt sta "${OUT}/sta-request.json" --pdk sky130A \
      --pdk-root "${PDK_ROOT}" --format json ) > "${OUT}/sta.json"
  _json_line "${OUT}/sta.json" 'd["status"], "geometry_source", d["geometry_source"], "worst setup slack", d["worst_slack_ns"], "ns; TNS", d["total_negative_slack_ns"], "ns;", d["setup_violation_count"], "setup violations; fmax", d["fmax_mhz"], "MHz"'
  _json_line "${OUT}/sta.json" '"  worst setup path:", d["worst_setup_path"]["startpoint"], "->", d["worst_setup_path"]["endpoint"], "at", d["worst_setup_path"]["slack_ns"], "ns"'
  # Stamp what this run measured (issue #218) -- see core_flow_sta_inputs.
  core_flow_sta_inputs
}

# core_flow_sta_inputs -- stamp what this core's timing run measured, into
# ${OUT}/sta-inputs.json beside the responses. For every file whose content
# determines THIS core's timing number -- each source resolved from
# sta-synth-request.json's sources (relative entries resolve against HERE,
# as klt resolves them), the committed sta-request.json and
# sta-synth-request.json templates, this flow's run.sh, and core_flow.sh
# itself (those four determine HOW the number was produced) -- it records
# the repo-relative path and a content hash spelled the way
# flow/common/record_lib.py's sha256() spells it, plus `git rev-parse HEAD`
# as a diagnostic field. The record generator
# (flow/common/make_timing_record.py) recomputes every stamped hash before a
# record is written and refuses on the first change, naming the file and the
# core to re-run: either run.sh --timing leaves scratch behind and the other
# core's --timing --record consumes it, so without this a record could stamp
# one revision while quoting the other core's measurement from an earlier
# one -- a window the generator's engine_version and liberty-deck checks
# cannot see, because it sits within one tool and deck generation (issue
# #218).
#
# The head is deliberately not the comparison key: HEAD moves for reasons
# unrelated to these files, and a rev-equality check would refuse a
# still-valid measurement whenever an unrelated commit landed between the
# two cores' runs. The generator cannot reuse a hash already sitting in the
# responses for the same reason it cannot compare them by hand: klt's
# provenance input.content_hash is a different quantity from a plain
# file-bytes hash. Called after the klt calls: set -e drops the run before
# this point on failure, and scratch without a stamp is refused by the
# generator exactly like scratch from before stamping existed.
core_flow_sta_inputs() {
  local head
  head="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
  python3 -I -c 'import hashlib, json, os, sys
here, out, repo_root, head = sys.argv[1:5]
repo_root = os.path.realpath(repo_root)
def stamp(path):
    real = os.path.realpath(path)
    if os.path.commonpath([real, repo_root]) != repo_root:
        sys.exit("sta: timing input resolves outside the repo: " + path)
    with open(real, "rb") as f:
        digest = "sha256:" + hashlib.sha256(f.read()).hexdigest()
    return {"path": os.path.relpath(real, repo_root), "content_hash": digest}
with open(os.path.join(here, "sta-synth-request.json")) as f:
    sources = json.load(f)["sources"]
inputs = [stamp(os.path.join(here, src)) for src in sources]
for name in ("sta-synth-request.json", "sta-request.json", "run.sh"):
    inputs.append(stamp(os.path.join(here, name)))
inputs.append(stamp(os.path.join(repo_root, "flow", "common", "core_flow.sh")))
inputs.sort(key=lambda entry: entry["path"])
with open(os.path.join(out, "sta-inputs.json"), "w") as f:
    json.dump({"head": head, "inputs": inputs}, f, indent=2)
    f.write("\n")' \
    "${HERE}" "${OUT}" "${REPO_ROOT}" "${head}"
  echo "sta: stamped timing inputs -> ${OUT}/sta-inputs.json (HEAD ${head:0:7})"
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
