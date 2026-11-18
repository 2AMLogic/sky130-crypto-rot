"""Shared bench plumbing for the cocotb benches in this directory: helpers
generic to any bench -- clock-cycle waits, fail accumulation -- rather than
part of the sibling port-protocol model in trngmodel.py.
"""

from cocotb.triggers import FallingEdge


async def cycles(d, n):
    for _ in range(n):
        await FallingEdge(d.clk)


class Checks:
    """Fail-accumulation mixin; the bench provides `self.fails` and reports it
    in its SUMMARY line."""

    def check(self, cond, msg):
        if not cond:
            self.fails.append(msg)
