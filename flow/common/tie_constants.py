#!/usr/bin/env python3
"""Rewrite bare Verilog literal constants in a `klt synthesize`-produced
gate-level netlist into a real standard-cell tie (`sky130_fd_sc_hd__conb_1`)
instance, so `klt place-and-route` (OpenROAD) can route the design.

## Why this exists (a real `klt` gap, not a workaround for this design)

`klt synthesize`'s Yosys script (`hierarchy` -> `synth` -> `dfflibmap` ->
`abc` -> `write_verilog -noattr`) never runs a `hilomap`-equivalent pass, so
any RTL construct that constant-propagates to a literal `0`/`1` (here:
`rtl/modexp.v`'s `mm_p2`/`mm_m1`/`mm_m2` zero-extension, e.g.
`assign mm_m1 = { 2'h0, mod_r };`) survives into the mapped netlist as a
*bare Verilog literal* instead of being driven by a real standard-cell
instance. OpenROAD's structural-Verilog reader accepts that literal fine at
`link_design` time (an implicit, unnamed net) and even carries it through
`initialize_floorplan`/`global_placement`/`clock_tree_synthesis` without
complaint -- but `detailed_route` (TritonRoute) rejects it outright:

    [ERROR DRT-0305] Net zero_ of signal type GROUND is not routable by
    TritonRoute. Move to special nets.

TritonRoute infers a constant-valued net as a power/ground *special* net
(this flow deliberately does no PDN generation -- see `flow/README.md`) and
refuses to route it as an ordinary signal, four stages after the netlist
that caused it was written and with no direct pointer back to the literal
that caused it. This is a `klt synthesize` output-contract gap (upstream
Yosys netlists commonly need a `hilomap`-equivalent lowering before any
place-and-router will accept them) -- filed generically, no design detail,
at `2AMLogic/klayout-tools` per this repo's `CLAUDE.md` friction protocol.
This script is the interim, repo-local fix: run once, between
`klt synthesize` and `klt place-and-route`, on any netlist containing a
literal constant.

## What it does

Finds every sized Verilog literal (`<width>'h..`/`'b..`/`'d..`/`'o..`) in
the netlist, expands it bit-by-bit (MSB first, matching Verilog
concatenation order) into references to one of two nets --
`_tie_zero_`/`_tie_one_` -- then adds a single
`sky130_fd_sc_hd__conb_1` instance (`.HI(_tie_one_)`, `.LO(_tie_zero_)`)
driving them, plus their `wire` declarations, before `endmodule`. Only the
nets actually used are declared/instantiated. Idempotent: a netlist with no
bare literals is copied through unchanged (no tie cell added).

Usage:
    python3 flow/tie_constants.py <in.v> <out.v>
"""

from __future__ import annotations

import re
import sys

_LITERAL_RE = re.compile(r"\b(\d+)'([hHbBdDoO])([0-9a-fA-F_xXzZ]+)\b")

_TIE_CELL = "sky130_fd_sc_hd__conb_1"
_ZERO_NET = "_tie_zero_"
_ONE_NET = "_tie_one_"
_TIE_INSTANCE = "_tie_cell_"


def _literal_bits(width: int, base: str, digits: str) -> list[str]:
    """Return `width` bits, MSB first, for a Verilog sized literal.

    Raises ValueError on `x`/`z` states or a malformed literal -- this
    script only handles fully-specified 0/1 constants, which is all a
    synthesized gate-level netlist should ever contain (Yosys does not
    emit `x`/`z` literals in mapped netlist output).
    """
    digits = digits.replace("_", "")
    if any(c in "xXzZ" for c in digits):
        raise ValueError(f"unsupported x/z literal: {width}'{base}{digits}")
    radix = {"h": 16, "b": 2, "d": 10, "o": 8}[base.lower()]
    value = int(digits, radix)
    if value >= (1 << width):
        raise ValueError(
            f"literal {width}'{base}{digits} value {value} exceeds its declared width"
        )
    return [str((value >> (width - 1 - i)) & 1) for i in range(width)]


def tie_constants(source: str) -> tuple[str, bool]:
    """Return `(rewritten_source, tie_cell_needed)`."""
    used = {"0": False, "1": False}

    def _replace(match: re.Match[str]) -> str:
        width = int(match.group(1))
        bits = _literal_bits(width, match.group(2), match.group(3))
        for bit in bits:
            used[bit] = True
        nets = [_ONE_NET if bit == "1" else _ZERO_NET for bit in bits]
        if width == 1:
            return nets[0]
        return "{ " + ", ".join(nets) + " }"

    rewritten = _LITERAL_RE.sub(_replace, source)
    tie_cell_needed = used["0"] or used["1"]
    if not tie_cell_needed:
        return rewritten, False

    decls = []
    if used["0"]:
        decls.append(f"  wire {_ZERO_NET};")
    if used["1"]:
        decls.append(f"  wire {_ONE_NET};")
    ports = []
    if used["1"]:
        ports.append(f"    .HI({_ONE_NET})")
    if used["0"]:
        ports.append(f"    .LO({_ZERO_NET})")
    instance = (
        f"  {_TIE_CELL} {_TIE_INSTANCE} (\n" + ",\n".join(ports) + "\n  );"
    )
    insertion = "\n".join(decls) + "\n" + instance + "\n"

    marker = "\nendmodule"
    if marker not in rewritten:
        raise ValueError("could not find 'endmodule' to insert the tie cell before")
    rewritten = rewritten.replace(marker, "\n" + insertion + "endmodule", 1)
    return rewritten, True


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} <in.v> <out.v>", file=sys.stderr)
        return 2
    in_path, out_path = argv[1], argv[2]
    with open(in_path, encoding="utf-8") as handle:
        source = handle.read()
    rewritten, tie_cell_needed = tie_constants(source)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(rewritten)
    if tie_cell_needed:
        print(f"{out_path}: inserted {_TIE_CELL} instance '{_TIE_INSTANCE}'")
    else:
        print(f"{out_path}: no bare literal constants found, copied unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
