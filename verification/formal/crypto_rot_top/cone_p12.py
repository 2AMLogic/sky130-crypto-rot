#!/usr/bin/env python3
"""P-12 (and the top-level P-2/P-14 structural checks) on the flattened
klt-synthesized netlist of crypto_rot_top (issue #88).

Usage: cone_p12.py DESIGN.json [--liberty FILE] [--expect pass|fail] [--out RESULT.json]

DESIGN.json is the Yosys write_json of the flattened `crypto_rot_top' top of
the klt-synthesized sky130_fd_sc_hd netlist, read through the PDK liberty
models (read_liberty + read_verilog + hierarchy -top crypto_rot_top + flatten
+ opt_clean). The graph is bit-level and CONSERVATIVE, the same encoding as
verification/formal/keyladder/cone.py: every output bit of a cell depends on
every input bit of that cell, and flops are ordinary cells, so a cone is the
full sequential fan-in "at every depth".

Checks, per spec/key-isolation-properties.md:

  P-12  no path from a key-bearing register (or the root_key input) to any
        output port or to a scan/test structure -- except through the P-4
        engine output carriers. The carriers (u_aes.state_q, the AES result
        the AES_DOUT window reads; u_hmac.core.hh, the digest the HMAC_MAC
        window reads; u_drbg.u_drbg.bd_q, the generate buffer the DRBG_OUT
        window reads) are CUT (treated as primary inputs) for dat_o's cone
        only, so any path that survives the cut is a key path that does NOT
        go through a defined result window. Every other output port is
        checked with NO cut at all: no key material may reach it by any
        route. Scan/DFT structure is checked by cell type (every cell must
        be a plain sky130_fd_sc_hd cell; with --liberty the pinned liberty is
        censused and every cell whose definition references a scan pin --
        SCD or SCE -- is refused whatever its name; scan/DFT/latch-named
        types are refused regardless) and by the port list (it must equal
        the RTL module's, so no debug/test/scan port was inserted).
  P-2   the same cone statement as P-12's first half, read at the top level:
        no slot flop in any output cone except through the engine datapath.
  P-14  trng_bus_re is constant (its cone is empty of real bits -- the
        sequencer never reads the sibling), and no trng_out_data bit reaches
        any output except as DRBG output (through the bd_q carrier, i.e. it
        is absent from every post-cut cone).
  P-10  structural clear-term fallback: the zeroize net `zr' is in the
        cone of every key-bearing register bit (every key register's next-
        state logic sees the zeroize term; the register-list completeness
        itself stays the review item the spec names).

Non-vacuity is machine-checked, not assumed: the carriers must have exactly
their RTL widths, every key net must exist, the carriers and the slot bits
must lie in dat_o's UNCUT cone (so the cut is load-bearing and the key really
is reachable through the engines), and zr must exist for P-10. A rename that
silently weakens any of this fails the run.

Register names survive klt synthesize as hierarchical wires, so the check
binds by name and asserts presence loudly. --expect pass on the committed
netlist is the P-12 proof of record; --expect fail on the mutant netlist
(the run.sh-generated copy of crypto_rot_top.v whose dat_o XORs hmac_key
bits into the read data) is the negative control.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import netlist_graph  # noqa: E402
from netlist_graph import build, cone  # noqa: E402

TOP = "crypto_rot_top"

# Key-bearing registers, by flat net name (klt synthesize keeps RTL names as
# hierarchical wires; run.sh's non-vacuity pass asserts each exists). Key
# material per spec/key-isolation-properties.md: root key (an input port,
# checked from ports), slot contents, AES round keys (both AES engines'),
# HMAC K0/inner, DRBG Key/V and the KDF/df working values, the seed buffer.
KEY_NETS = (
    "u_kdf.s0", "u_kdf.s1", "u_kdf.s2", "u_kdf.s3",
    "u_hmac.k0", "u_hmac.inner",
    "u_aes.rk_q",
    "u_drbg.u_drbg.key_q", "u_drbg.u_drbg.v_q", "u_drbg.u_drbg.prov_q",
    "u_drbg.u_drbg.chain_q", "u_drbg.u_drbg.tk_q", "u_drbg.u_drbg.tx_q",
    "u_drbg.u_drbg.t0_q",
    "u_drbg.u_aes.rk_q", "u_drbg.u_aes.state_q",
    "u_drbg.u_if.seed_q",
)
KEY_INPUT_PORTS = ("root_key",)
# Sibling outputs: must reach the bus only as DRBG output (through bd_q).
FOREIGN_INPUT_PORTS = ("trng_out_data",)

# P-4 result carriers: the registers whose bits are allowed to carry key
# material to dat_o, with the widths the RTL fixes. Exactly these bits are
# cut, for dat_o's cone only.
CARRIERS = (("u_aes.state_q", 128), ("u_hmac.core.hh", 256), ("u_drbg.u_drbg.bd_q", 128))
CARRIER_PORTS = ("u_aes", "u_hmac", "u_drbg")  # the engine instances (labels only)

ZEROIZE_NET = "zr"

# Plain standard-cell naming, checked on the FLATTENED netlist: flatten maps
# each liberty cell to internal `$_*' primitives and leaves a `$scopeinfo'
# marker carrying the original module name in attributes.module, with its
# parameters.TYPE naming "cell" (a standard cell) or "module" (a design
# hierarchy boundary). Every cell scope must name a plain sky130_fd_sc_hd
# cell (no scan/DFT/debug/low-power/latch type); every module scope must be
# one of this design's own modules. sky130_fd_sc_hd DOES ship scan-capable
# cells, so a DFT insertion can surface as ordinary-looking cell scopes.
# Scan capability is matched on the PROPERTY, not on a remembered family
# list: --liberty censuses the pinned liberty and refuses every cell whose
# definition references a scan pin (`SCD' or `SCE'), whatever its name. The
# name arm below stays as defense-in-depth (any scan/DFT-named cell, the
# dl* latches, lpflow_*/probe*, and every `sky130_fd_sc_hd__s*' name -- on
# the pinned liberty that prefix is exactly the scan-capable set, measured).
CELL_PREFIX = "sky130_fd_sc_hd__"
CELL_DENY = re.compile(r"scan|dft|probe|lpflow|bscan|boundary|^sky130_fd_sc_hd__dl|^sky130_fd_sc_hd__s")
LIB_CELL_RE = re.compile(r'^\s*cell\s*\(\s*"([^"]+)"\s*\)')
LIB_PIN_RE = re.compile(r'^\s*pin\s*\(\s*"([^"]+)"\s*\)')
SCAN_PINS = ("SCD", "SCE")
DESIGN_MODULE_RE = re.compile(
    r"^(?:\\\$paramod\$[0-9a-f]+\\)?(?:keyladder|hmac_sha256|aes_core|sha256_core|ctr_drbg|drbg_top|trng_if)$")

# RTL ports: read from the RTL module header so the comparison cannot drift
# from a hand-maintained list.
PORT_RE = re.compile(r"^\s*(input|output|inout)\s+(?:wire|reg)?\s*(?:\[\s*(\d+)\s*:\s*(\d+)\s*\])?\s*(\w+)")


def rtl_ports(path: str) -> dict[str, str]:
    ports: dict[str, str] = {}
    in_module = False
    for line in open(path):
        if not in_module:
            if re.match(r"\s*module\s+" + TOP + r"\b", line):
                in_module = True
            continue
        if re.match(r"\s*endmodule\b", line):
            break
        m = PORT_RE.match(line)
        if m:
            ports[m.group(4)] = m.group(1)
    if not ports:
        raise SystemExit(f"no ports parsed from {path} (module {TOP} header changed?)")
    return ports


def liberty_scan_cells(path: str) -> dict:
    """Census the liberty: every cell whose definition references a scan pin
    (`SCD' or `SCE') is scan-capable, whatever its name. The result feeds the
    cell-scope check so the gate tracks the PDK instead of a name prefix.
    Raises SystemExit if no cell block parses -- a parse failure must not
    look like a scan-free liberty."""
    scan: dict[str, str] = {}
    n_cells = 0
    cur = None
    depth = 0
    for line in open(path, errors="replace"):
        if cur is None:
            m = LIB_CELL_RE.match(line)
            if m:
                cur = m.group(1)
                n_cells += 1
                depth = line.count("{") - line.count("}")
            continue
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            cur = None
            continue
        m = LIB_PIN_RE.match(line)
        if m and m.group(1) in SCAN_PINS:
            scan[cur] = re.sub(r"_\d+$", "", cur.removeprefix(CELL_PREFIX))
    if n_cells == 0:
        raise SystemExit(f"liberty {path}: no cell block parsed; refusing to "
                         "run the cell-scope check without the scan census")
    return {"cells": n_cells, "scan_capable": scan,
            "families": sorted(set(scan.values()))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("design")
    ap.add_argument("--rtl", help="rtl/crypto_rot_top.v (port-list comparison)")
    ap.add_argument("--liberty", help="pinned liberty (.lib): censused for SCD/SCE scan "
                    "pins; every scan-capable cell name is refused by the cell-scope check")
    ap.add_argument("--expect", choices=("pass", "fail"), default="pass")
    ap.add_argument("--splice-scope", metavar="MODULE",
                    help="negative control: splice one extra $scopeinfo marker naming "
                         "MODULE before the checks (e.g. a scan/probe cell type) -- "
                         "the cell-scope check must fire")
    ap.add_argument("--splice-port", metavar="PORT",
                    help="negative control: splice one extra output port PORT before "
                         "the checks -- the port-list check must fire")
    ap.add_argument("--out")
    args = ap.parse_args()

    top = netlist_graph.load(args.design, TOP, strict=True)
    if args.splice_scope:
        top["cells"]["_splice_scope_control"] = {
            "type": "$scopeinfo", "hide_name": 0, "parameters": {"TYPE": "module"},
            "attributes": {"module": args.splice_scope},
            "port_directions": {}, "connections": {},
        }
    if args.splice_port:
        bits = [b for b in next(iter(top["netnames"].values()))["bits"] if isinstance(b, int)]
        top["netnames"]["_splice_port_control"] = {"hide_name": 0, "bits": bits}
        top["ports"][args.splice_port] = {"direction": "output", "bits": bits}
    drivers, ins = build(top)
    nets = top["netnames"]
    lib_census = liberty_scan_cells(args.liberty) if args.liberty else None

    def bits_of(name):
        rec = nets.get(name)
        if rec is None:
            raise SystemExit(f"net {name} not found in the flattened netlist "
                             "(register names did not survive synthesis?)")
        return [b for b in rec["bits"] if isinstance(b, int)]

    failures: list[str] = []
    result: dict = {"design": args.design, "checks": {}, "violations": []}

    # ---- ports: no scan/test/debug port inserted --------------------------
    if args.rtl:
        want = rtl_ports(args.rtl)
        got = {p: v["direction"] for p, v in top["ports"].items()}
        extra = sorted(set(got) - set(want))
        missing = sorted(set(want) - set(got))
        wrong = sorted(p for p in set(got) & set(want) if got[p] != want[p])
        result["checks"]["ports"] = {"rtl": len(want), "netlist": len(got),
                                     "extra": extra, "missing": missing, "wrong_direction": wrong}
        if extra or missing or wrong:
            failures.append(f"port list differs from the RTL (extra: {extra}; missing: {missing}; "
                            f"wrong direction: {wrong})")
    else:
        result["checks"]["ports"] = "skipped (--rtl not given)"

    # ---- cell scopes: plain sky130_fd_sc_hd cells only --------------------
    # ($scopeinfo markers left by flatten carry each instance's original
    # module name; see CELL_PREFIX above. The internal `$_*' primitives are
    # the liberty cells' flattened implementations; anything else is foreign.)
    scopeinfo = [c for c in top["cells"].values() if c["type"] == "$scopeinfo"]
    bad_scopes: list[str] = []
    n_cell_scopes = 0
    for c in scopeinfo:
        mod = c.get("attributes", {}).get("module", "")
        # liberty cells keep their sky130 name; design boundaries keep the
        # RTL module name (a $scopeinfo's parameters.TYPE says "module" for
        # both, so the prefix is the classifier)
        if mod.startswith(CELL_PREFIX):
            n_cell_scopes += 1
            if CELL_DENY.search(mod) or (lib_census is not None and mod in lib_census["scan_capable"]):
                bad_scopes.append(mod)
        elif not DESIGN_MODULE_RE.match(mod):
            bad_scopes.append(mod)
    foreign_types = sorted(t for t in {c["type"] for c in top["cells"].values()}
                           if t != "$scopeinfo" and not t.startswith("$_"))
    result["checks"]["cell_scopes"] = {"scopeinfo": len(scopeinfo),
                                       "cell_scopes": n_cell_scopes,
                                       "offending": bad_scopes, "foreign_types": foreign_types,
                                       "liberty_census": lib_census or "skipped (--liberty not given)"}
    if bad_scopes:
        failures.append(f"non-plain or scan/DFT-style cells present: {bad_scopes[:10]}"
                        + (f" (+{len(bad_scopes) - 10} more)" if len(bad_scopes) > 10 else ""))
    if foreign_types:
        failures.append(f"cell types that are neither scope markers nor internal primitives: {foreign_types}")
    if n_cell_scopes == 0:
        failures.append("no $scopeinfo cell scopes found: the cell-type check would be vacuous")

    # ---- bit sets ----------------------------------------------------------
    key: dict[int, str] = {}
    key_nets: dict[str, list[int]] = {}
    for n in KEY_NETS:
        bs = bits_of(n)
        key_nets[n] = bs
        key.update({b: n for b in bs})
    foreign: dict[int, str] = {}
    for pn in FOREIGN_INPUT_PORTS:
        foreign.update({b: pn for b in top["ports"][pn]["bits"] if isinstance(b, int)})
    key_inputs: dict[int, str] = {}
    for pn in KEY_INPUT_PORTS:
        key_inputs.update({b: pn for b in top["ports"][pn]["bits"] if isinstance(b, int)})

    carriers: dict[str, list[int]] = {}
    cut: set[int] = set()
    for n, w in CARRIERS:
        bs = bits_of(n)
        if len(bs) != w:
            failures.append(f"carrier {n} has {len(bs)} bits, expected {w} (RTL width)")
        carriers[n] = bs
        cut.update(bs)

    # ---- cones --------------------------------------------------------------
    out_cones = {}
    for pname, port in top["ports"].items():
        if port["direction"] != "output":
            continue
        c = cone(port["bits"], drivers, ins, cut if pname == "dat_o" else frozenset())
        out_cones[pname] = c

    # P-12/P-2/P-14: no key/foreign bit in any output cone (dat_o's after the
    # carrier cut, every other port's raw).
    for pname, c in sorted(out_cones.items()):
        hit = sorted({key[b] for b in c if b in key})
        hit_in = sorted({key_inputs[b] for b in c if b in key_inputs})
        hit_f = sorted({foreign[b] for b in c if b in foreign})
        result["checks"].setdefault("output_cones", {})[pname] = {
            "cone_bits": len(c),
            "key_nets": hit, "key_inputs": hit_in, "foreign_inputs": hit_f,
            "carrier_cut": pname == "dat_o",
        }
        if hit or hit_in or hit_f:
            failures.append(f"output {pname} depends on key/foreign material: "
                            f"{hit + hit_in + hit_f}")

    # P-14: trng_bus_re constant (its cone holds no real bit at all).
    re_cone = cone(top["ports"]["trng_bus_re"]["bits"], drivers, ins)
    result["checks"]["trng_bus_re"] = {"cone_bits": len(re_cone)}
    if re_cone:
        failures.append("trng_bus_re is not constant (cone of "
                        f"{len(re_cone)} bits; the sequencer must never read the sibling)")

    # P-10 structural fallback: zr in the cone of every key register (one
    # register-level cone per net: the clear term must reach the register's
    # next-state logic; per-bit cones share it by construction of the load
    # mux, and the register is the granularity the spec's P-10 names).
    zr = bits_of(ZEROIZE_NET)
    no_clear = []
    for n, bs in key_nets.items():
        if zr[0] not in cone(bs, drivers, ins):
            no_clear.append(n)
    result["checks"]["p10_clear_terms"] = {"registers": len(key_nets),
                                           "without_zr_term": sorted(no_clear)}
    if no_clear:
        failures.append(f"key registers without a zr clear term: {sorted(no_clear)}")

    # ---- non-vacuity --------------------------------------------------------
    dat_o_uncut = cone(top["ports"]["dat_o"]["bits"], drivers, ins)
    nonvac = {
        "carriers_in_dat_o_uncut": {n: len([b for b in bs if b in dat_o_uncut])
                                    for n, bs in carriers.items()},
        "slots_in_dat_o_uncut": len([b for b in key_nets["u_kdf.s0"] if b in dat_o_uncut]),
        "root_key_bits_in_dat_o_uncut": len([b for b in top["ports"]["root_key"]["bits"]
                                             if isinstance(b, int) and b in dat_o_uncut]),
        "trng_out_data_bits_in_dat_o_uncut": len([b for b in top["ports"]["trng_out_data"]["bits"]
                                                  if isinstance(b, int) and b in dat_o_uncut]),
        "key_bits_total": len(key),
    }
    result["non_vacuity"] = nonvac
    if any(v == 0 for v in nonvac["carriers_in_dat_o_uncut"].values()):
        failures.append("a P-4 carrier does not reach dat_o's uncut cone: the cut would be decorative")
    if nonvac["slots_in_dat_o_uncut"] == 0 or nonvac["root_key_bits_in_dat_o_uncut"] == 0:
        failures.append("key material is not reachable through the engines: the check would be vacuous")
    if nonvac["key_bits_total"] == 0:
        failures.append("no key register bits found")

    result["violations"] = failures
    result["status"] = "pass" if not failures else "fail"

    for pname, r in result["checks"].get("output_cones", {}).items():
        tag = "carrier-cut" if r["carrier_cut"] else "uncut"
        print(f"  {pname:16s} [{tag:11s}] cone={r['cone_bits']:7d} bits  "
              f"key: {r['key_nets'] or r['key_inputs'] or r['foreign_inputs'] or 'none'}")
    print(f"P-12 netlist check: {result['status'].upper()} (violations: {failures or 'none'})")
    if args.out:
        json.dump(result, open(args.out, "w"), indent=2, sort_keys=True)
    return 0 if result["status"] == args.expect else 1


if __name__ == "__main__":
    sys.exit(main())
