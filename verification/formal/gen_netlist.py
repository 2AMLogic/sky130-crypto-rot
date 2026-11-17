#!/usr/bin/env python3
"""Stage the netlist half of verification/formal/run.sh (issue #177). Standard library only.

The P-7/P-8/P-9 property text lives in the RTL under `ifdef FORMAL
(rtl/drbg/ctr_drbg.v, rtl/trng_if/trng_if.v) and nothing under rtl/ is edited.
Everything the netlist SymbiYosys runs read is generated here, in two phases:

  --prepare    rtl_<variant>.v    ctr_drbg.v preprocessed/mutated for the mutant
                                  syntheses (iverilog -E; klt synthesize takes no
                                  defines and no parameter overrides, so the
                                  negative controls and the interval-1 runs are
                                  source-mutated copies -- 2AMLogic/klayout-tools
                                  #4196/#4698). Also copies tb_net_probe.v.
  --netlist    dut_net_<v>.v      the `ctr_drbg' (or `trng_if') module of a
                                  klt-synthesized netlist with the RTL property
                                  text spliced in: `fv_zero' (and `fv_alarm_s2')
                                  rebuilt as ports from the surviving register
                                  wires, localparam/parameter names replaced by
                                  numeric literals derived by parsing the RTL,
                                  and `op_q' bound over the bits synthesis kept.
                 if_net_clean.v   the same for `trng_if' (clean netlist only).
                 fv_drbg_net.v    the tracked wrappers with only the
                 fv_p9_net.v      instantiation parameter lists removed (a
                                  netlist module has none); the property and
                                  assertion text is unchanged.

The `synth' pass re-encodes detected FSMs: `state_q' survives at its RTL width
with the RTL binary assignment, but `op_q' was re-coded (2 -> 3 bits, one flop
optimized away), so OP_GEN cannot be a fixed literal. --netlist probes each
variant's netlist (flatten with the pinned yosys, directed icarus run of
tb_net_probe.v: instantiate, then generate; read op_q after each accepted
command; the wheel's own `sat` command traps at this design size,
2AMLogic/klayout-tools#5804, so the probe simulates instead) and binds OP_GEN as a conjunction over the bits synthesis kept -- a
bit synthesis optimized away reads z here and is an unconstrained net in the
formal run, so it must not appear in the binding. The generated copies carry
machine-checked binding assertions (`busy == (state_q != S_IDLE)' and
`state_q == S_GEN_ISSUE |-> <op==OP_GEN>') so a later re-synthesis that
re-encodes a register fails loudly instead of silently weakening the proof.
Register survival (name and width) is checked per module; a missing or
re-widthed register fails the run rather than binding to nothing.
"""

from __future__ import annotations

import argparse
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DRBG_RTL = REPO / "rtl/drbg/ctr_drbg.v"
TRNG_RTL = REPO / "rtl/trng_if/trng_if.v"

# The textual interval mutation of the source used for the interval-1 syntheses
# (the parameter default; $clog2(RESEED_INTERVAL + 2) follows automatically).
INTERVAL_FROM = "parameter RESEED_INTERVAL = 65536"
INTERVAL_TO = "parameter RESEED_INTERVAL = 1"

DRBG_VARIANTS = ("clean", "interval", "neg_interval", "neg_seeded", "neg_zeroize")
# Registers the property text names, as (name, expected RTL width or None) --
# `op_q' is present but deliberately NOT width-checked: synth's fsm pass
# re-encodes it (see module docstring).
DRBG_REGS = [
    ("key_q", 128), ("v_q", 128), ("chain_q", 128), ("tk_q", 128),
    ("tx_q", 128), ("t0_q", 128), ("prov_q", 256), ("bd_q", 128),
    ("bv_q", None), ("bl_q", None), ("seeded_q", None), ("state_q", 4),
    ("ctr_q", "ctr"), ("op_q", None), ("ocnt_q", None),
]
TRNG_REGS = [
    ("seed_q", 512), ("ready_q", None), ("collecting_q", None),
    ("ordy_q", None), ("a2", None),
]


def die(msg: str):
    print(f"gen_netlist: {msg}", file=sys.stderr)
    raise SystemExit(1)


def formal_blocks(rtl_text: str, module: str) -> tuple[str, str]:
    """(port block, body block): the first and last `ifdef FORMAL' regions.

    In both RTL files the first `ifdef FORMAL' declares the fv_* output ports
    and the last one (before `endmodule') holds the property text. Anything
    else is refused: the extraction must stay pinned to what it verifies.
    """
    regions = [m.group(1) for m in
               re.finditer(r"^`ifdef FORMAL\n(.*?)^`endif\n", rtl_text, re.M | re.S)]
    if len(regions) < 2:
        die(f"{module}: expected >=2 `ifdef FORMAL regions, found {len(regions)}")
    ports, body = regions[0], regions[-1]
    if "output" not in ports:
        die(f"{module}: first `ifdef FORMAL region declares no output ports")
    if "assert" not in body and "assign" not in body:
        die(f"{module}: last `ifdef FORMAL region holds no assertions/assigns")
    return ports, body


def localparam(rtl_text: str, name: str) -> str:
    m = re.search(rf"\b{name} = (\d+'d\d+)\b", rtl_text)
    if not m:
        die(f"localparam {name} not found in the RTL; the literal binding would be a guess")
    return m.group(1)


def param_default(rtl_text: str, name: str) -> int:
    m = re.search(rf"parameter\s+{name}\s*=\s*(\d+)\b", rtl_text)
    if not m:
        die(f"parameter {name} default not found in the RTL")
    return int(m.group(1))


def module_text(netlist: str, module: str) -> str:
    m = re.search(rf"^module {re.escape(module)}\b", netlist, re.M)
    if not m:
        die(f"module {module} not in netlist")
    end = netlist.index("\nendmodule", m.end()) + len("\nendmodule\n")
    return netlist[m.start():end]


def add_port(mod: str, port: str) -> str:
    """Add an `output <port>; wire <port>;' port to a yosys-written netlist module.

    Insertion only: the port name joins the header list, the two declarations
    go in front of the existing port declarations, and removing both again
    restores the original bytes.
    """
    m = re.search(r"^module \w+\(", mod, re.M)
    if not m:
        die("netlist module header not found")
    # The header closes at its first `);'; yosys wraps long port lists, so the
    # close is not always preceded by a newline (trng_if's is wrapped).
    close = mod.index(");", m.end())
    out = mod[:close] + f", {port}" + mod[close:]
    decl_at = out.index("\n", close) + 1
    decls = f"  output {port};\n  wire {port};\n"
    out = out[:decl_at] + decls + out[decl_at:]
    reverted = out.replace(f", {port}", "", 1).replace(decls, "", 1)
    if reverted != mod:
        die(f"port insertion for {port} is not a pure insertion")
    return out


def splice(mod: str, block: str) -> str:
    """Insert block before the module's final `endmodule'; pure insertion."""
    end = mod.index("\nendmodule")
    out = mod[:end + 1] + block + "\n" + mod[end + 1:]
    assert out.replace(block + "\n", "", 1) == mod, "splice altered the netlist module"
    return out


def check_registers(mod: str, regs, ctr_width: int, module: str) -> None:
    missing, wrong = [], []
    for name, width in regs:
        if width == "ctr":
            width = ctr_width
        m = re.search(rf"^\s*wire\s+(?:\[(\d+):0\]\s+)?{re.escape(name)};", mod, re.M)
        if not m:
            missing.append(name)
        elif width is not None:
            have = int(m.group(1)) + 1 if m.group(1) else 1
            if have != width:
                wrong.append(f"{name} (expected width {width}, netlist declares "
                             f"width {have})")
    if missing or wrong:
        die(f"{module}: register binding failed -- missing: {missing or '[]'}; "
            f"width mismatch: {wrong or '[]'}")


def parse_probe_patterns(stdout: str, stderr: str, variant: str) -> tuple[str, str]:
    """(INST, GEN) op_q patterns as tb_net_probe printed them, MSB first.

    `$display("%b", ...)` emits one unspaced run per line, so the pattern is
    captured whole: the old `{3}` bound here silently truncated a wider op_q
    to its first three characters and bound the wrong bits (issue #206). The
    captured token is validated whole against the `%b` alphabet 01xXzZ: a
    permissive capture class alone would silently truncate at the first
    out-of-class character (a simulator-swap trap, issue #219) where `{3}`
    failed loudly. Both patterns must appear; their widths are checked where
    they are bound.
    """
    pats = dict(re.findall(r"(OP_AFTER_INST|OP_AFTER_GEN)=(\S+)", stdout))
    for name, pat in pats.items():
        bad = "".join(sorted(set(pat) - set("01xXzZ")))
        if bad:
            die(f"op_q probe for {variant}: {name}={pat} has character(s) "
                f"outside the %b alphabet 01xXzZ ({bad}); the probe or the "
                "simulator changed output format -- refusing to bind a "
                "truncated pattern")
    if "PROBE_FAIL" in stdout or len(pats) != 2:
        die(f"op_q probe for {variant} did not produce both patterns; output:\n"
            f"{stdout}\n{stderr}")
    return pats["OP_AFTER_INST"], pats["OP_AFTER_GEN"]


def opgen_binding(inst_pat: str, gen_pat: str, variant: str) -> str:
    """The op_q == OP_GEN conjunction over the driven bits, Verilog-indexed.

    `%b` prints MSB first, so bit i of the netlist's op_q is
    reversed(gen_pat)[i]; reading the string left to right swapped the two
    driven bits (issue #206), harmless only while the GEN pattern stayed
    symmetric over them. The conjunction must also be false for the INST
    pattern: the property text's `op_q != OP_GEN' is replaced by its negation,
    so a conjunction satisfied in more op states than OP_GEN silently weakens
    the P-8 reseed term. Checked here, at generation time, it costs no solver
    time and adds no proof obligation -- unlike a netlist-side negative
    assertion, which would need every variant re-proven.
    """
    if len(inst_pat) != len(gen_pat):
        die(f"op_q probe for {variant}: INST and GEN patterns disagree in width "
            f"(inst={inst_pat} is {len(inst_pat)} bits, gen={gen_pat} is "
            f"{len(gen_pat)} bits); the probe or the netlist changed shape")
    gen_bits = list(reversed(gen_pat))   # %b is MSB first: index i here is op_q[i]
    driven = [(bit, b) for bit, b in enumerate(gen_bits) if b in "01"]
    if not driven:
        die(f"op_q probe for {variant}: no driven bits")
    inst_bits = list(reversed(inst_pat))
    if all(inst_bits[bit] == b for bit, b in driven):
        die(f"op_q probe for {variant}: the OP_GEN binding is also satisfied by the "
            f"INST pattern (inst={inst_pat}, gen={gen_pat}); the conjunction is too "
            "wide to stand in for `op_q != OP_GEN'")
    return "(" + " && ".join(f"op_q[{bit}] == 1'b{b}" for bit, b in driven) + ")"


def probe_opgen(stage: Path, variant: str, lib: str, net: Path, tb: Path) -> str:
    """The driven-bit conjunction for op_q == OP_GEN, for one variant netlist.

    Flatten with the pinned yosys and read the accepted-command op_q patterns
    with icarus (the wheel's `sat' traps on this design). The conjunction is
    over the bits synthesis kept: a bit it optimized away reads z in the probe
    and is an unconstrained net in the formal run, so it must stay out of the
    binding. INST and GEN must differ over those bits, or the ops would not be
    distinguishable and the P-8 assertion would bind to nothing.
    """
    flat = stage / f"flat_{variant}.v"
    # The yowasp runtime preopens its own sandbox temp dir AS /tmp, so absolute
    # /tmp paths resolve inside the sandbox: read the netlist through a relative
    # path (the cwd preopen) with a copy in the stage directory.
    src_copy = stage / f"probe_src_{variant}.v"
    shutil.copyfile(net, src_copy)
    r = subprocess.run(
        ["yosys", "-p", (
            f"read_liberty -ignore_miss_func {lib}\n"
            f"read_verilog {src_copy.name}\n"
            "hierarchy -top ctr_drbg\nflatten\nopt_clean\n"
            f"write_verilog -noattr {flat.name}")],
        cwd=stage, capture_output=True, text=True)
    src_copy.unlink()
    if r.returncode != 0:
        die(f"flatten for the {variant} op_q probe failed:\n"
            f"{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    r = subprocess.run(["iverilog", "-o", f"probe_{variant}.vvp", str(tb), flat.name],
                       cwd=stage, capture_output=True, text=True)
    if r.returncode != 0:
        die(f"probe compile for {variant} failed:\n{r.stderr}")
    r = subprocess.run(["vvp", f"probe_{variant}.vvp"], cwd=stage,
                       capture_output=True, text=True)
    inst_pat, gen_pat = parse_probe_patterns(r.stdout, r.stderr, variant)
    return opgen_binding(inst_pat, gen_pat, variant)


def strip_instantiation_params(wrapper: str, name: str, from_str: str, to_str: str) -> str:
    n = wrapper.count(from_str)
    if n != 1:
        die(f"{name}: expected exactly one instantiation parameter list "
            f"({from_str!r}), found {n}")
    return wrapper.replace(from_str, to_str)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=Path, required=True)
    ap.add_argument("--prepare", action="store_true",
                    help="mutant RTL sources + probe bench (before synthesis)")
    ap.add_argument("--netlist", action="append", default=[], metavar="NAME=PATH",
                    help="synthesized netlist variant, e.g. clean=.../ctr_drbg_synth.v")
    ap.add_argument("--lib", required=True, help="sky130_fd_sc_hd liberty file")
    args = ap.parse_args()
    st = args.stage
    st.mkdir(parents=True, exist_ok=True)

    drbg = DRBG_RTL.read_text()
    trng = TRNG_RTL.read_text()
    s_idle = localparam(drbg, "S_IDLE")
    s_gen_issue = localparam(drbg, "S_GEN_ISSUE")
    s_upd_wait = localparam(drbg, "S_UPD_WAIT")
    interval = param_default(drbg, "RESEED_INTERVAL")
    inst_words = param_default(drbg, "INST_WORDS")
    reseed_words = param_default(drbg, "RESEED_WORDS")

    if args.prepare:
        if drbg.count(INTERVAL_FROM) != 1:
            die("interval mutation site not found exactly once; rtl changed?")
        (st / "rtl_clean.v").write_text(drbg)
        (st / "rtl_interval.v").write_text(drbg.replace(INTERVAL_FROM, INTERVAL_TO))
        for name, define, src in (
            ("neg_interval", "DRBG_NEG_INTERVAL", st / "rtl_interval.v"),
            ("neg_seeded", "DRBG_NEG_SEEDED", DRBG_RTL),
            ("neg_zeroize", "DRBG_NEG_ZEROIZE", DRBG_RTL),
        ):
            r = subprocess.run(["iverilog", "-E", f"-D{define}", "-o",
                                str(st / f"rtl_{name}.v"), str(src)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                die(f"iverilog -E -D{define} failed:\n{r.stderr}")
        shutil.copyfile(HERE / "tb_net_probe.v", st / "tb_net_probe.v")
        return 0

    nets = {}
    for item in args.netlist:
        name, path = item.split("=", 1)
        nets[name] = Path(path)
    for required in DRBG_VARIANTS + ("if_clean",):
        if required not in nets:
            die(f"--netlist {required}=... missing")
    tb = st / "tb_net_probe.v"
    if not tb.exists():
        die("tb_net_probe.v not staged; run --prepare first")

    # --- ctr_drbg variants -------------------------------------------------
    ports_d, body_d = formal_blocks(drbg, "ctr_drbg")
    fv_zero_d = re.search(r"output\s+wire\s+(\w+),", ports_d).group(1)

    wrappers = {}
    for target, src_name, pairs in (
        ("fv_drbg_net.v", "fv_drbg.v",
         [("ctr_drbg #(.INST_WORDS(16), .RESEED_WORDS(8), .RESEED_INTERVAL(INTERVAL)) dut (",
           "ctr_drbg dut (")]),
        ("fv_p9_net.v", "fv_p9.v",
         [("trng_if #(.INST_WORDS(16), .RESEED_WORDS(8)) u_if (", "trng_if u_if ("),
          ("ctr_drbg #(.INST_WORDS(16), .RESEED_WORDS(8), .RESEED_INTERVAL(65536)) u_drbg (",
           "ctr_drbg u_drbg (")]),
    ):
        text = (HERE / src_name).read_text()
        for frm, to in pairs:
            text = strip_instantiation_params(text, target, frm, to)
        wrappers[target] = text

    for variant in DRBG_VARIANTS:
        net = module_text(nets[variant].read_text(), "ctr_drbg")
        interval_here = 1 if variant in ("interval", "neg_interval") else interval
        ctr_width_here = int(math.log2(interval_here + 2)) + 1   # $clog2(RESEED_INTERVAL + 2)
        check_registers(net, DRBG_REGS, ctr_width_here, f"ctr_drbg[{variant}]")
        op_gen_conj = probe_opgen(st, variant, args.lib, nets[variant], tb)
        body = body_d
        if body.count("op_q != OP_GEN") != 1:
            die(f"{variant}: `op_q != OP_GEN' not found exactly once in the "
                "formal block; the RTL changed?")
        body = body.replace("op_q != OP_GEN", f"!{op_gen_conj}")
        for name, lit in (("S_IDLE", s_idle), ("S_GEN_ISSUE", s_gen_issue),
                          ("S_UPD_WAIT", s_upd_wait),
                          ("RESEED_INTERVAL", str(interval_here))):
            body = re.sub(rf"\b{name}\b", lit, body)
        if re.search(r"\b(S_IDLE|S_GEN_ISSUE|S_UPD_WAIT|OP_GEN|RESEED_INTERVAL)\b", body):
            die(f"{variant}: an unbound localparam name survived the literal "
                "substitution")
        checks = (
            "\n    // netlist binding checks (generated by gen_netlist.py; not part of\n"
            "    // the RTL property text): the literals above are this netlist's own\n"
            "    // encodings, re-checked here so a re-synthesis that re-encodes a\n"
            "    // register fails loudly instead of silently weakening the proof.\n"
            f"    always @* if (f_on) assert (busy == (state_q != {s_idle}));\n"
            f"    always @* if (f_on && state_q == {s_gen_issue}) assert {op_gen_conj};\n")
        (st / f"dut_net_{variant}.v").write_text(splice(add_port(net, fv_zero_d),
                                                        body + checks))

    # --- trng_if -----------------------------------------------------------
    # P-9 needs only the fv_zero/fv_alarm_s2 reconstruction; the RTL region's
    # other assertions (word cleanliness, sequencer whitelist, bus_re) are
    # other properties, not this issue's, and would need their own binding
    # (their localparams and internal wires are not netlist-stable).
    ports_t, body_t = formal_blocks(trng, "trng_if")
    fv_ports_t = re.findall(r"output\s+wire\s+(\w+),", ports_t)
    if fv_ports_t != ["fv_zero", "fv_alarm_s2"]:
        die(f"trng_if fv ports changed: {fv_ports_t}")
    fv_assigns = [ln for ln in body_t.splitlines() if ln.strip().startswith("assign fv_")]
    if len(fv_assigns) != 2 or not fv_assigns[0].strip().startswith("assign fv_zero"):
        die("trng_if formal region does not hold the two expected fv_* assigns; "
            "the RTL changed?")
    seedw = 32 * max(inst_words, reseed_words)
    body_t = "\n".join(fv_assigns) + "\n"
    body_t = re.sub(r"\bSEEDW\b", str(seedw), body_t)
    if re.search(r"\bSEEDW\b", body_t):
        die("trng_if: SEEDW survived the literal substitution")
    net = module_text(nets["if_clean"].read_text(), "trng_if")
    check_registers(net, TRNG_REGS, 0, "trng_if")
    for port in fv_ports_t:
        net = add_port(net, port)
    (st / "if_net_clean.v").write_text(splice(net, body_t))

    for name, text in wrappers.items():
        (st / name).write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
