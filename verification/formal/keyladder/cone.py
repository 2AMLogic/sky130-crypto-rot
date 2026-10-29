#!/usr/bin/env python3
"""P-2: structural cone-of-influence check on a flattened Yosys JSON netlist (issue #56).

Usage: cone.py DESIGN.json [--expect pass|fail] [--out RESULT.json]

DESIGN.json is `write_json` of the flattened top module `keyladder` (RTL after
`proc; flatten; techmap`, or the klt-synthesized netlist read through the PDK
liberty models). The graph is bit-level and CONSERVATIVE: every output bit of a
cell depends on every input bit of that cell, and flops are ordinary cells (a flop's
Q depends on D, clock, enable, reset), so the cone is the full sequential fan-in.

Check (the P-2 statement): for every output port other than the engine key outputs
hmac_key and aes_key, no bit of the slot value registers s0..s3 is in its cone.
The same cone is also checked against the key-material INPUTS (root_key, ld_data) and
the HMAC K0 / inner-digest and SHA-256 datapath registers (where their names survive
in the design under check): if none of them is in the sequential fan-in of a non-key
output, that output is a function of non-key inputs and non-key state only, at every
depth. That is a conservative structural sufficient condition for the module-boundary
P-1 (it does not by itself say the cone registers start equal in two runs; the bounded
2-copy check covers reset-to-depth). Non-vacuity: the cones of hmac_key and aes_key DO
contain slot bits.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque

ENGINE_KEY_OUTPUTS = ("hmac_key", "aes_key")
SLOT_NETS = ("s0", "s1", "s2", "s3")
KEY_INPUT_PORTS = ("root_key", "ld_data")


def load(path: str):
    top = None
    data = json.load(open(path))
    for name, mod in data["modules"].items():
        if mod.get("attributes", {}).get("top") or name == "keyladder":
            top = mod
    if top is None:
        raise SystemExit("top module keyladder not found")
    return top


def build(top):
    # bit -> list of cell indices that drive it; cell index -> list of input bits
    drivers: dict[int, list[int]] = {}
    ins: list[list[int]] = []
    for idx, cell in enumerate(top["cells"].values()):
        dirs = cell.get("port_directions", {})
        cin: list[int] = []
        for port, bits in cell["connections"].items():
            d = dirs.get(port)
            if d is None:
                raise SystemExit(f"cell type {cell['type']} port {port} has no direction; "
                                 "design is not fully flattened/modelled")
            for b in bits:
                if not isinstance(b, int):
                    continue
                if d == "input":
                    cin.append(b)
                else:
                    drivers.setdefault(b, []).append(idx)
        ins.append(cin)
    return drivers, ins


def cone(bits, drivers, ins):
    seen = set()
    cells = set()
    q = deque(b for b in bits if isinstance(b, int))
    while q:
        b = q.popleft()
        if b in seen:
            continue
        seen.add(b)
        for c in drivers.get(b, ()):
            if c in cells:
                continue
            cells.add(c)
            q.extend(ins[c])
    return seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("design")
    ap.add_argument("--expect", choices=("pass", "fail"), default="pass")
    ap.add_argument("--out")
    args = ap.parse_args()

    top = load(args.design)
    drivers, ins = build(top)
    nets = top["netnames"]

    def bits_of(name):
        return [b for b in nets[name]["bits"] if isinstance(b, int)]

    # Key-bearing bit sets, by category. "slots" and "key_inputs" are required (P-2 and
    # the structural form of the module-boundary P-1); "hmac_state" and "sha_datapath"
    # are enforced for the names that survive in the design under check.
    cats: dict[str, dict[int, str]] = {"slots": {}, "key_inputs": {}, "hmac_state": {},
                                       "sha_datapath": {}}
    for n in SLOT_NETS:
        if n not in nets:
            raise SystemExit(f"net {n} not found (names did not survive?)")
        for b in bits_of(n):
            cats["slots"][b] = n
    for pn in KEY_INPUT_PORTS:
        for b in top["ports"][pn]["bits"]:
            if isinstance(b, int):
                cats["key_inputs"][b] = pn
    sha_names = {f"prf.core.{x}" for x in ("w", "hh", "a", "b", "c", "d", "e", "f", "g", "h")}
    for name, rec in nets.items():
        cat = ("hmac_state" if name in ("prf.k0", "prf.inner") else
               "sha_datapath" if name in sha_names else None)
        if cat:
            for b in rec["bits"]:
                if isinstance(b, int):
                    cats[cat][b] = name

    result = {"design": args.design,
              "bits": {c: len(v) for c, v in cats.items()},
              "outputs": {}, "violations": []}
    for pname, port in top["ports"].items():
        if port["direction"] != "output":
            continue
        c = cone(port["bits"], drivers, ins)
        hit = {cat: sorted({m[b] for b in c if b in m}) for cat, m in cats.items()}
        allowed = pname in ENGINE_KEY_OUTPUTS
        result["outputs"][pname] = {"width": len(port["bits"]), "cone_bits": len(c),
                                    "key_bearing_in_cone": {k: v for k, v in hit.items() if v},
                                    "engine_key_output": allowed}
        if not allowed and any(hit.values()):
            result["violations"].append(pname)
    nonvac = all(result["outputs"][p]["key_bearing_in_cone"].get("slots")
                 for p in ENGINE_KEY_OUTPUTS)
    result["non_vacuous"] = bool(nonvac)
    result["status"] = "pass" if (not result["violations"] and nonvac) else "fail"

    for p, r in result["outputs"].items():
        tag = "engine key output" if r["engine_key_output"] else "non-key output"
        print(f"  {p:12s} [{tag}] cone={r['cone_bits']:6d} bits  key-bearing in cone: "
              f"{r['key_bearing_in_cone'] or 'none'}")
    print(f"P-2 cone check: {result['status'].upper()} "
          f"(violations: {result['violations'] or 'none'}; non-vacuous: {result['non_vacuous']})")
    if args.out:
        json.dump(result, open(args.out, "w"), indent=2, sort_keys=True)
    return 0 if result["status"] == args.expect else 1


if __name__ == "__main__":
    sys.exit(main())
