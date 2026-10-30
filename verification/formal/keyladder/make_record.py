#!/usr/bin/env python3
"""Verdict (and optionally record) for the key ladder formal flow run by run.sh.

Reads the SymbiYosys work directories and the P-2 cone results under --stage. Fails
(exit 1) unless every run meets its expectation:

  * proofs (P-5, P-6 on RTL and netlist) PASS;
  * every negative control FAILS with a counterexample trace (a property without a
    mutation that breaks it is not accepted: the table MUTATIONS is checked);
  * every cover run reaches all its cover statements;
  * the bounded module-boundary P-1 runs PASS to their depth or stop at the time limit
    (the depth reached is recorded); a counterexample or error is a failure.

With no --check-only it also writes an append-only record under
verification/records/keyladder-formal/records/. Standard library only.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import platform
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "flow/common"))

from record_lib import pin, run, sha256  # noqa: E402
EXPERIMENT = "keyladder-formal"
HERE = "verification/formal/keyladder"
INPUTS = (
    "rtl/sha256/sha256_core.v",
    "rtl/hmac/hmac_sha256.v",
    "rtl/keyladder/keyladder.v",
    f"{HERE}/props_slots.vh",
    f"{HERE}/hmac_abstract.v",
    f"{HERE}/p1_product.v",
    f"{HERE}/p5.sby",
    f"{HERE}/p6.sby",
    f"{HERE}/p1.sby",
    f"{HERE}/cover.sby",
    f"{HERE}/cone.py",
    f"{HERE}/gen.py",
    f"{HERE}/latency_tb.v",
    f"{HERE}/run.sh",
    f"{HERE}/make_record.py",
    "spec/key-isolation-properties.md",
    "scripts/setup-env.sh",
)

# property -> (mutation, what it breaks, the run that must fail). Checked below.
MUTATIONS = {
    "P-5": ("KL_NEG_MASK (existing `ifdef` in keyladder.v)", "HMAC use-mask bit not checked", ("p5", "neg_rtl"), ("p5", "neg_net")),
    "P-6": ("KL_NEG_LOCK (existing `ifdef` in keyladder.v)", "lock not checked on a write", ("p6", "neg_rtl"), ("p6", "neg_net")),
    "P-1": ("slot-path mutant (generated copy; `busy` ORs in s0[0])", "one slot -> non-key-output path", ("p1", "neg_rtl"), ("p1", "neg_net")),
}
# (sby file, task) -> expectation
EXPECT = {
    ("p5", "rtl"): "PASS", ("p5", "net"): "PASS", ("p5", "neg_rtl"): "FAIL", ("p5", "neg_net"): "FAIL",
    ("p6", "rtl"): "PASS", ("p6", "net"): "PASS", ("p6", "neg_rtl"): "FAIL", ("p6", "neg_net"): "FAIL",
    ("cover", "cover"): "PASS", ("p1", "cover"): "PASS",
    ("p1", "neg_rtl"): "FAIL", ("p1", "neg_net"): "FAIL",
    ("p1", "rtl"): "BOUNDED", ("p1", "net"): "BOUNDED",
}
CONES = {"rtl": "pass", "net": "pass", "rtl_slotpath": "fail", "net_slotpath": "fail"}


def collect(stage: Path, sby: str, task: str) -> dict:
    d = stage / (sby if sby == "cover" else f"{sby}_{task}")
    r = {"sby": sby, "task": task, "status": "MISSING", "elapsed_s": None, "steps_checked": None,
         "induction_step": None, "cex_step": None, "trace": None, "covers": None}
    st = d / "status"
    if not st.exists():
        return r
    r["status"] = st.read_text().split()[0]
    log = (d / "logfile.txt").read_text()
    steps = [int(m) for m in re.findall(r"Checking (?:assertions|assumptions and assertions) in step (\d+)", log)]
    steps += [int(m) for m in re.findall(r"Checking cover reachability in step (\d+)", log)]
    r["steps_checked"] = max(steps) if steps else None
    m = re.findall(r"Trying induction in step (\d+)", log)
    if "Temporal induction successful" in log and m:
        r["induction_step"] = int(m[-1])
    m = re.search(r"failed assertion .* step (\d+)", log)
    if m:
        r["cex_step"] = int(m.group(1))
    t = sorted((d / "engine_0").glob("trace*.vcd")) if (d / "engine_0").exists() else []
    r["trace"] = bool(t)
    r["covers"] = len(re.findall(r"Reached cover statement", log))
    m = re.search(r"Elapsed clock time \[H:MM:SS \(secs\)\]: (\d+):(\d+):(\d+)", log)
    if m:
        r["elapsed_s"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    return r


def judge(res: dict) -> tuple[bool, str]:
    exp = EXPECT[(res["sby"], res["task"])]
    s = res["status"]
    if exp == "PASS":
        return s == "PASS", f"expected PASS, got {s}"
    if exp == "FAIL":
        return s == "FAIL" and res["trace"], f"expected FAIL with a counterexample trace, got {s}" + ("" if res["trace"] else " (no trace)")
    return s in ("PASS", "TIMEOUT"), f"expected PASS or TIMEOUT (depth recorded), got {s}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=Path, required=True)
    ap.add_argument("--pdk-root", type=Path, required=True)
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--p1-depth-rtl", type=int, required=True)
    ap.add_argument("--p1-depth-net", type=int, required=True)
    ap.add_argument("--prove-depth", type=int, required=True)
    ap.add_argument("--p6-net-depth", type=int, required=True)
    args = ap.parse_args()
    st = args.stage

    runs = {k: collect(st, *k) for k in EXPECT}
    ok = True
    lines = []
    for (sby, task), res in runs.items():
        good, why = judge(res)
        ok &= good
        lines.append(f"  {sby}:{task:8s} {res['status']:8s} {'ok' if good else 'UNEXPECTED: ' + why}")
    cones = {}
    for name, want in CONES.items():
        f = st / f"cone_{name}.result.json"
        cones[name] = json.loads(f.read_text()) if f.exists() else {"status": "missing"}
        good = cones[name]["status"] == want
        ok &= good
        lines.append(f"  cone:{name:13s} {cones[name]['status']:8s} {'ok' if good else 'UNEXPECTED: expected ' + want}")
    for prop, (_, _, rtl_run, net_run) in MUTATIONS.items():
        for k in (rtl_run, net_run):
            if k not in EXPECT or EXPECT[k] != "FAIL":
                ok = False
                lines.append(f"  {prop}: mutation run {k} not registered as a must-fail run")
    print("keyladder formal:\n" + "\n".join(lines))
    lat = (st / "latency.txt").read_text() if (st / "latency.txt").exists() else ""
    m = re.search(r"DERIVE_LATENCY_CYCLES=(\d+) err=(\d)", lat)
    if not m or m.group(2) != "0":
        ok = False
        print("  derive latency not measured / derive refused")
    print("RESULT:", "PASS" if ok else "FAIL")
    if not ok:
        return 1
    if args.check_only:
        return 0

    latency = int(m.group(1))
    sources = (args.pdk_root / "sky130A/SOURCES").read_text()
    if pin("CIEL_SKY130_VERSION") not in sources:
        raise SystemExit("PDK tree does not name the pinned open_pdks commit; refusing to record")
    z3_sha = hashlib.sha256((REPO / ".venv/bin/z3").read_bytes()).hexdigest()
    if z3_sha != pin("Z3_BIN_SHA256"):
        raise SystemExit("z3 binary does not match the pin; refusing to record")
    rev = run("git", "-C", str(REPO), "rev-parse", "HEAD")
    if subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--"] + list(INPUTS),
                      capture_output=True, text=True).stdout.strip():
        raise SystemExit("an input is modified relative to HEAD; commit it before recording")
    now = datetime.datetime.now(datetime.timezone.utc)
    rid = f"{now:%Y%m%d-%H%M%S}-{rev[:7]}"
    venv_py = REPO / ".venv/bin/python3"
    wasm = run(str(venv_py), "-c",
               "import hashlib,os,yowasp_yosys as y;print('sha256:'+hashlib.sha256(open(os.path.join(os.path.dirname(y.__file__),'yosys.wasm'),'rb').read()).hexdigest())")
    versions = {
        "yosys": run(str(REPO / ".venv/bin/yosys"), "-V"),
        "yowasp_yosys": pin("YOWASP_YOSYS_VERSION"),
        "yosys_wasm": wasm,
        "sby": "SymbiYosys from the yowasp-yosys wheel (yowasp-sby)",
        "z3": run(str(REPO / ".venv/bin/z3"), "--version"),
        "z3_solver_wheel": pin("Z3_SOLVER_VERSION"),
        "z3_binary": "sha256:" + z3_sha,
        "klt_pin": pin("KLT_VERSION"),
        "icarus": run("iverilog", "-V"),
        "python": platform.python_version(),
    }
    meta = {"record_id": rid, "experiment": EXPERIMENT, "supersedes": None, "git_revision": rev,
            "provenance": {"tool_versions": versions,
                           "inputs": [{"path": p, "content_hash": sha256(REPO / p)} for p in INPUTS]}}

    def row(sby, task, what, mode, depth):
        r = runs[(sby, task)]
        if r["status"] == "PASS":
            how = []
            if r["induction_step"] is not None:
                how.append(f"induction closed (smtbmc tried steps {depth}..{r['induction_step']})")
            res = "PASS" + (" -- " + "; ".join(how) if how else "")
        elif r["status"] == "FAIL":
            res = f"FAIL, counterexample at step {r['cex_step']}" if r["cex_step"] is not None else "FAIL, counterexample"
        else:
            reached = (r["steps_checked"] - 1) if r["steps_checked"] else None
            res = (f"{r['status']}: no assertion violation in steps 0..{reached}; the check of step "
                   f"{r['steps_checked']} did not finish") if reached is not None else r["status"]
        t = f"{r['elapsed_s']} s" if r["elapsed_s"] is not None else "n/a"
        return f"| {what} | {mode} | {depth} | {res} | {t} |"

    P = args.prove_depth
    rows = [
        row("p5", "rtl", "P-5 on RTL", "prove (BMC + k-induction), abstract HMAC", P),
        row("p5", "net", "P-5 on netlist", "prove, abstract HMAC", P),
        row("p5", "neg_rtl", "P-5 negative control, RTL (mask check dropped)", "prove", P),
        row("p5", "neg_net", "P-5 negative control, netlist from the mutant", "prove", P),
        row("p6", "rtl", "P-6 on RTL", "prove, abstract HMAC", P),
        row("p6", "net", "P-6 on netlist", "prove, abstract HMAC", args.p6_net_depth),
        row("p6", "neg_rtl", "P-6 negative control, RTL (lock check dropped)", "prove", P),
        row("p6", "neg_net", "P-6 negative control, netlist from the mutant", "prove", P),
        row("cover", "cover", "P-5/P-6 non-vacuity covers (RTL)", "cover", 80),
        row("p1", "cover", "P-1 product non-vacuity covers", "cover", 32),
        row("p1", "rtl", "P-1 module boundary on RTL (real HMAC/SHA-256)", "bmc", args.p1_depth_rtl),
        row("p1", "net", "P-1 module boundary on netlist", "bmc", args.p1_depth_net),
        row("p1", "neg_rtl", "P-1 negative control, RTL (slot -> busy path)", "bmc", 32),
        row("p1", "neg_net", "P-1 negative control, netlist from the mutant", "bmc", 32),
    ]
    cone_rows = []
    for name, label in (("rtl", "RTL"), ("net", "synthesized netlist"),
                        ("rtl_slotpath", "negative control, RTL (slot -> busy)"),
                        ("net_slotpath", "negative control, netlist from the mutant")):
        c = cones[name]
        cone_rows.append(f"| {label} | {c['status'].upper()} | {', '.join(c['violations']) or 'none'} | "
                         f"{', '.join(k for k, v in c['bits'].items() if v)} |")

    p1r, p1n = runs[("p1", "rtl")], runs[("p1", "net")]

    def p1_state(r, depth):
        if r["status"] == "PASS":
            return f"no non-key-output difference in steps 0..{depth} (BMC depth {depth} completed)"
        return (f"time limit reached: no difference in steps 0..{r['steps_checked'] - 1}; "
                f"the configured depth {depth} was NOT reached") if r["steps_checked"] else r["status"]

    body = f"""<!-- record-meta
{json.dumps(meta, indent=2)}
-->

# Record {rid}

- **Record ID**: {rid}
- **Claim**: bounded formal results for `rtl/keyladder/keyladder.v` (issue #56), and nothing beyond the depths and abstractions stated here. Rows are labelled with the `spec/key-isolation-properties.md` property they address. No security, certification or side-channel claim is made.
- **Design provenance**: P-5/P-6: RTL, and the `keyladder` module of the `klt synthesize` sky130_fd_sc_hd netlist (liberty corner `tt_025C_1v80`, pre-P&R) read through the PDK liberty functional models (`read_liberty -ignore_miss_func`); the netlist cells are modelled by Yosys from the liberty `function`/`ff` groups, no hand-written cell models. P-2 and P-1: RTL, and the full synthesized netlist.
- **Run configuration**: `./scripts/setup-env.sh` then `./verification/formal/keyladder/run.sh --record`. Engine `smtbmc z3`, single solver, no portfolio. P-1 bounded depths configured: RTL {args.p1_depth_rtl}, netlist {args.p1_depth_net}.
- **Property text**: P-5, P-6 and the covers are `{HERE}/props_slots.vh`, spliced unchanged into a generated COPY of `keyladder.v` (and of the netlist's `keyladder` module); `gen.py` checks the splice is a pure insertion. `rtl/keyladder/keyladder.v` is not modified. Registers named by the properties (`s0..s3 v0..v3 m0..m3 l0..l3 d0..d3 state dst par_root par_sel`) survive synthesis as named wires, so one text covers both.
- **Abstraction (P-5, P-6 only)**: `hmac_sha256` is replaced by `hmac_abstract.v`, whose every output is an unconstrained per-cycle input. Any behaviour of the real core is a behaviour of the stand-in, and these two properties constrain only the ladder's own registers, so a proof over the stand-in holds for the real core. The run starts in the post-reset state (every register named above at its reset value; the HMAC/SHA-256 datapath free).

## Results

| Run | Mode | Depth | Result | Wall time |
|---|---|---|---|---|
{chr(10).join(rows)}

"Induction closed (smtbmc tried steps N..M)" is the solver's own log line (the last "Trying induction in step" before "Temporal induction successful"); the BMC base case of the same run is configured to the depth in the Depth column. The P-6 netlist run is configured at depth {args.p6_net_depth} because its BMC base case grows steeply beyond about 11 steps on the mapped design (a run at depth 16 was stopped by hand at step 12 after more than five minutes in that step); its proof rests on the induction, which closes with the invariants below. P-6 on RTL also closes at induction depth 1 (checked by hand at depths 1, 2, 3).

### P-5 (slot used only if the use-mask bit is set at the time of use)

Statement (`props_slots.vh`, `-DP5`): `hmac_key != 0` implies `hmac_req`, the slot valid, and mask bit 2; `aes_key != 0` implies `aes_req`, the slot valid and mask bit 1 (decrypt) or 0 (encrypt); in the START state with a slot parent, the parent is valid with mask bit 3 (KDF-parent). Proven at BMC depth {P} plus induction, on RTL and on the netlist (rows above). It needs no strengthening invariant: the statement is combinational over the current state.

### P-6 (locked slot cannot be written or have its mask changed until zeroize/reset)

Statement (`-DP6`): if slot n was locked at the previous edge and neither `zeroize` nor reset was applied at it, then the slot is still locked and valid and its value, mask and depth are unchanged. Induction claim with these strengthening invariants (all asserted in the same run, so each is itself proven inductively): I1 `state <= 5`; I2 `state != IDLE` implies the destination slot is not locked (locks are only accepted in IDLE; derive/load are only accepted into an unlocked slot); I3 a lock implies the slot is valid. Ablation on RTL (by hand, each invariant removed alone): without I2 the run ends UNKNOWN (the induction step fails: an in-flight derivation can commit into a locked destination from an unreachable state); without I1 or without I3 the run still passes, so they are not needed at this depth and are kept as checked invariants.

### P-2 (no output depends on slot flops except through the engine key inputs)

Structural cone-of-influence check (`cone.py`) on the flattened design: bit-level, conservative (every cell output depends on every cell input; flops are cells, so the cone is the full sequential fan-in). For each output other than `hmac_key`/`aes_key`, no bit of `s0..s3` is in its cone. The same cone was also checked against the key-material inputs `root_key` and `ld_data` and the HMAC K0/inner and SHA-256 datapath registers (names that survive in the design under check). Non-vacuity: the cones of `hmac_key` and `aes_key` do contain slot bits.

| Design | Result | Violating outputs | Key-bearing categories checked |
|---|---|---|---|
{chr(10).join(cone_rows)}

### P-1 at the module boundary

Two copies of `keyladder` share every input except the key material (`root_key`, `ld_data`; `cmd_ctx` is the 0003 public user_context and is shared); asserted: every output other than `hmac_key`/`aes_key` is equal in both copies in every cycle from the first post-reset cycle. The two copies start with independent free contents in the registers that have no reset (the SHA-256 datapath). The real HMAC and SHA-256 core are in the product (no abstraction).

- **Longest operation**: one root derivation takes {latency} clock cycles from the command to `done_pulse` (Icarus, `latency_tb.v`; +-1 for the edge convention). The earlier curation estimate was "at least 260" (the HMAC's hash work alone); the measured figure includes the byte-serial feed.
- **RTL**: {p1_state(p1r, args.p1_depth_rtl)}.
- **Netlist**: {p1_state(p1n, args.p1_depth_net)}.
- **Not proven**: a derivation (about {latency} cycles) is NOT covered by the bounded runs above unless a configured depth reached {latency}; per the spec's Open question 1 the property stays at the depth reached. No induction claim is made for P-1: it would need the equality of every control register of both copies as a strengthening invariant, which was not attempted.
- **Structural complement, not a substitute for the bounded result**: the P-2 cone check above also finds none of the key inputs, slot registers, HMAC K0/inner or SHA-256 datapath registers in the sequential fan-in of any non-key output. A non-key output is therefore a function of non-key inputs and non-key registers only, at every depth; this is a conservative sufficient condition and does not by itself show that the registers in those cones start equal in two runs (the bounded run covers reset-to-depth). Reading it as the unbounded P-1 would go beyond the evidence in two ways it does not close: register initial values without reset, and the soundness of the flattening/liberty modelling used here.
- **Bus-level P-1** (`dat_o`/`ack`/`err`/`irq`) needs the bus front end and is issue #46's; it is not claimed here.
- **Non-vacuity**: the product covers reach states where the two copies' `hmac_key` and `aes_key` differ, both copies are busy, and a load completes (row "P-1 product non-vacuity covers"). The P-5/P-6 covers reach: a root derivation and a slot-parent derivation start, a derivation is captured, a lock is set, a write to a locked slot is refused, a mask change is refused, HMAC and AES (enc and dec) releases are granted and a release is denied.

### Negative controls (each must make its proof fail)

| Property | Mutation | Breaks | Runs that fail |
|---|---|---|---|
{chr(10).join(f'| {p} | {m} | {b} | `{a[0]}:{a[1]}`, `{n[0]}:{n[1]}` |' for p, (m, b, a, n) in MUTATIONS.items())}
| P-2 | the slot-path mutant above | one slot -> `busy` path | cone check on RTL and on the netlist synthesized from the mutant |

The netlist negative controls are separate `klt synthesize` runs of the mutated RTL (preprocessed with the `KL_NEG_*` define for the two existing ones), so the failing proof is on a mapped netlist, not an RTL argument.

### Limits and known gaps

- Netlist results are for the `klt synthesize` output of this RTL at one liberty corner, read through Yosys's own liberty-derived models. Placed or routed netlists, scan/DFT structures and P-12 were not examined. P-13 (equivalence of netlist to RTL) was not attempted; the RTL and netlist rows are separate proofs of the same text, not one carried to the other.
- P-5/P-6 are about the ladder's registers and release logic, over an abstract HMAC; they say nothing about the HMAC core. P-4 (release only to the permitted consumer) and bus-level behaviour are other issues'.
- The slot properties are stated over the ports and named registers listed above; a property of a register this text does not name is not covered.
- Known limitation carried from the issue #55 record: `hmac_sha256` `clear` does not clear the SHA-256 datapath registers; this record neither depends on nor changes that.
- Nothing here is a certification, validation or side-channel claim.

- **Tool versions**: Yosys {versions['yosys']} (yowasp-yosys {versions['yowasp_yosys']}, `yosys.wasm` {wasm}); SymbiYosys and `yosys-smtbmc` from the same wheel; {versions['z3']} (z3-solver {versions['z3_solver_wheel']}, binary {versions['z3_binary']}); klt pinned at `{versions['klt_pin']}` (synthesis); {versions['icarus']}; Python {versions['python']}.
- **Links**: `{HERE}/`, `rtl/keyladder/keyladder.v`, `spec/key-isolation-properties.md` (P-1, P-2, P-5, P-6, Open questions 1-3), `verification/records/keyladder-sim-synth/`.
- **Timestamp / author**: {now:%Y-%m-%dT%H:%M:%SZ}, Loom builder agent (issue #56).
- **Supersedes**: none
"""
    out = REPO / "verification/records" / EXPERIMENT / "records" / f"{rid}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body)
    print("wrote", out.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
