#!/usr/bin/env python3
"""Shared netlist helpers for the formal flows (issue #277).

Stated once, used by both proof flows: the bit-level cone-of-influence model
(`load`/`build`/`cone`) walks the flattened Yosys `write_json' netlists of
verification/formal/keyladder/cone.py (module-level P-2) and
verification/formal/crypto_rot_top/cone_p12.py (top-level P-12/P-2/P-14/P-10),
and the module-text helpers (`module_text`/`splice`) stage the property
splices of verification/formal/keyladder/gen.py and
verification/formal/gen_netlist.py. The graph is bit-level and CONSERVATIVE:
every output bit of a cell depends on every input bit of that cell, and flops
are ordinary cells (a flop's Q depends on D, clock, enable, reset), so a cone
is the full sequential fan-in "at every depth". A future fix to this model or
to the pure-insertion splice discipline lands here, once, and every flow
moves together -- a miss here would leave one proof flow checking a different
graph than the other, on the property that matters most to this block.
"""

from __future__ import annotations

import json
import re
from collections import deque


def load(path: str, top: str):
    """The top module of a Yosys `write_json' netlist, selected by name.

    The `top' attribute (write_json sets it on the `hierarchy -top' module)
    is accepted as an alternative marker, last match wins. Raises SystemExit
    when no module matches -- a missing top must stop the run, not return a
    wrong module.
    """
    top_mod = None
    data = json.load(open(path))
    for name, mod in data["modules"].items():
        if mod.get("attributes", {}).get("top") or name == top:
            top_mod = mod
    if top_mod is None:
        raise SystemExit(f"top module {top} not found in {path}")
    return top_mod


def build(top):
    """The conservative bit-level dependency index of a flattened module.

    Returns (drivers, ins): net id -> the indices of the cells that drive it,
    and per cell the list of its input bits. A cell port without a direction
    raises SystemExit: the design under check must be fully
    flattened/modelled, or the graph would silently miss paths.
    """
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


def cone(bits, drivers, ins, cut=frozenset()):
    """The sequential fan-in of `bits`, as the set of reachable net ids.

    `cut` bits are treated as primary inputs: they seed nothing and are never
    followed, so the walk stops at them (the P-4 result-carrier cut, which
    keeps any path that survives it out of the defined result windows).
    """
    seen = set()
    cells = set()
    q = deque(b for b in bits if isinstance(b, int) and b not in cut)
    while q:
        b = q.popleft()
        if b in seen:
            continue
        seen.add(b)
        for c in drivers.get(b, ()):
            if c in cells:
                continue
            cells.add(c)
            q.extend(x for x in ins[c] if x not in cut)
    return seen


def module_text(netlist: str, module: str) -> str:
    """The whole `module ... endmodule' text of `module` in a netlist file."""
    m = re.search(rf"^module {re.escape(module)}\b", netlist, re.M)
    if not m:
        raise SystemExit(f"module {module} not in netlist")
    end = netlist.index("\nendmodule", m.end()) + len("\nendmodule\n")
    return netlist[m.start():end]


def splice(text: str, block: str, module: str | None = None) -> str:
    """Insert `block` before a module's final `endmodule`; a pure insertion.

    With `module`, the insertion point is that module's `endmodule` in the
    full text (splicing a property file into the RTL or into one module of a
    multi-module netlist); without it, `text` is already one module's text,
    as cut out by `module_text`. The assertion is the splice check: removing
    the block again must give back the original bytes.
    """
    if module is not None:
        m = re.search(rf"^module {re.escape(module)}\b", text, re.M)
        if not m:
            raise SystemExit(f"module {module} not found")
        end = text.index("\nendmodule", m.end())
    else:
        end = text.index("\nendmodule")
    out = text[:end + 1] + block + "\n" + text[end + 1:]
    assert out.replace(block + "\n", "", 1) == text, "splice altered the source"
    return out
