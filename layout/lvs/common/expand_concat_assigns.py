#!/usr/bin/env python3
"""Expand concatenation-RHS ``assign`` statements in a gate-level Verilog
netlist into one plain ``assign <net> = <net>;`` per bit.

Why this exists
---------------

``klt lvs``'s ``reference.form: "gate-level-verilog"`` reads a `klt
place-and-route`-shaped gate-level Verilog netlist directly as the LVS
reference, which is what unlocks two things this repo needs and its older
``plain-element`` SPICE reference structurally cannot provide:

* the native power-only-cell prune (``topology.power_only_pruned``) that
  removes the layout side's filler/tapcell circuits before comparing, and
* the ``power_connectivity`` verdict block, which is the only way `klt lvs`
  answers the power/ground question at all for a signal-only reference.

Its Verilog reader, however, accepts only a plain ``assign <net> = <net>;``
alias and raises on a concatenation right-hand side::

    assign mm_p2 = { mm_p, _tie_zero_ };

Yosys emits that shape routinely for a vector assignment, so the netlist
this repo already has — ``modexp_synth_tied.v``, frozen evidence under
``verification/records/`` and never edited in place — cannot be handed to
that form as-is. Filed upstream, generically, as
`2AMLogic/klayout-tools#2372 <https://github.com/2AMLogic/klayout-tools/issues/2372>`_.

This script is the disclosed, mechanical work-around: it rewrites *only*
concatenation-RHS ``assign`` statements into the per-bit plain form the
reader already accepts, bit-for-bit equivalent to what the concatenation
denotes. Nothing else in the netlist is touched — every ``module`` port,
``wire`` declaration and cell instantiation is copied through byte for
byte — so the connectivity the LVS compare sees is the frozen netlist's
own. Retire it once the upstream issue lands.

Usage
-----

::

    python3 layout/lvs/expand_concat_assigns.py <input.v> <output.v>

Exits non-zero (and writes nothing) if a concatenation cannot be expanded
bit-exactly — an unknown width, a replication operator, a literal, or a
part-select — rather than guessing.
"""

from __future__ import annotations

import re
import sys

_WIDTH_DECL = re.compile(
    r"^\s*(?:input|output|inout|wire|reg)\s+\[\s*(-?\d+)\s*:\s*(-?\d+)\s*\]\s*"
    r"([A-Za-z_$][\w$]*)\s*;"
)
_SCALAR_DECL = re.compile(
    r"^\s*(?:input|output|inout|wire|reg)\s+([A-Za-z_$][\w$]*)\s*;"
)
_ASSIGN = re.compile(r"^(\s*)assign\s+(.+?)\s*=\s*(.+?)\s*;\s*$")
_BIT_SELECT = re.compile(r"^([A-Za-z_$][\w$]*)\s*\[\s*(-?\d+)\s*\]$")
_IDENT = re.compile(r"^[A-Za-z_$][\w$]*$")


class ExpandError(RuntimeError):
    """A concatenation this script refuses to guess at."""


def collect_widths(lines: list[str]) -> dict[str, tuple[int, int]]:
    """Map every declared net name to its ``(msb, lsb)``.

    A scalar declaration maps to ``(0, 0)``. A net declared more than once
    (Yosys emits ``input x; wire x;``) keeps the first ranged declaration
    it has, since that is the one that carries the width.
    """
    widths: dict[str, tuple[int, int]] = {}
    for line in lines:
        ranged = _WIDTH_DECL.match(line)
        if ranged is not None:
            msb, lsb, name = int(ranged.group(1)), int(ranged.group(2)), ranged.group(3)
            widths[name] = (msb, lsb)
            continue
        scalar = _SCALAR_DECL.match(line)
        if scalar is not None:
            widths.setdefault(scalar.group(1), (0, 0))
    return widths


def _bits_of(name: str, widths: dict[str, tuple[int, int]]) -> list[str]:
    """Expand a whole-net reference into its bit references, MSB first."""
    if name not in widths:
        raise ExpandError(f"net {name!r} has no width declaration")
    msb, lsb = widths[name]
    if (msb, lsb) == (0, 0):
        return [name]
    step = -1 if msb >= lsb else 1
    return [f"{name}[{index}]" for index in range(msb, lsb + step, step)]


def _operand_bits(operand: str, widths: dict[str, tuple[int, int]]) -> list[str]:
    """Expand one concatenation operand into bit references, MSB first."""
    operand = operand.strip()
    if not operand:
        raise ExpandError("empty concatenation operand")
    if operand.startswith("{") and operand.endswith("}"):
        return _concat_bits(operand, widths)
    bit = _BIT_SELECT.match(operand)
    if bit is not None:
        if bit.group(1) not in widths:
            raise ExpandError(f"net {bit.group(1)!r} has no width declaration")
        return [f"{bit.group(1)}[{int(bit.group(2))}]"]
    if _IDENT.match(operand):
        return _bits_of(operand, widths)
    raise ExpandError(
        f"operand {operand!r} is not a plain net, bit-select or nested "
        "concatenation (literals, replications and part-selects are not "
        "expanded — extend this script rather than guessing)"
    )


def _split_top_level(body: str) -> list[str]:
    """Split a concatenation body on commas that are not inside braces."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in body:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                raise ExpandError("unbalanced '}' in concatenation")
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    if depth != 0:
        raise ExpandError("unbalanced '{' in concatenation")
    parts.append("".join(current))
    return parts


def _concat_bits(expr: str, widths: dict[str, tuple[int, int]]) -> list[str]:
    expr = expr.strip()
    if not (expr.startswith("{") and expr.endswith("}")):
        raise ExpandError(f"{expr!r} is not a concatenation")
    bits: list[str] = []
    for operand in _split_top_level(expr[1:-1]):
        bits.extend(_operand_bits(operand, widths))
    return bits


def expand(text: str) -> tuple[str, int]:
    """Return ``(rewritten text, number of statements expanded)``."""
    lines = text.splitlines(keepends=True)
    widths = collect_widths(lines)
    out: list[str] = []
    expanded = 0
    for line in lines:
        match = _ASSIGN.match(line)
        if match is None or "{" not in match.group(3):
            out.append(line)
            continue
        indent, lhs, rhs = match.group(1), match.group(2), match.group(3)
        rhs_bits = _concat_bits(rhs, widths)
        lhs_bits = _operand_bits(lhs, widths)
        if len(lhs_bits) != len(rhs_bits):
            raise ExpandError(
                f"width mismatch expanding 'assign {lhs} = {rhs};': "
                f"{len(lhs_bits)} left-hand bit(s) vs {len(rhs_bits)} "
                "right-hand bit(s)"
            )
        out.append(
            f"{indent}// expanded from: assign {lhs} = {rhs};"
            "  (layout/lvs/expand_concat_assigns.py)\n"
        )
        for lhs_bit, rhs_bit in zip(lhs_bits, rhs_bits):
            out.append(f"{indent}assign {lhs_bit} = {rhs_bit};\n")
        expanded += 1
    return "".join(out), expanded


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "usage: expand_concat_assigns.py <input.v> <output.v>",
            file=sys.stderr,
        )
        return 2
    with open(argv[1], encoding="utf-8") as handle:
        text = handle.read()
    try:
        rewritten, count = expand(text)
    except ExpandError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    with open(argv[2], "w", encoding="utf-8") as handle:
        handle.write(rewritten)
    print(f"expanded {count} concatenation assign(s) -> {argv[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
