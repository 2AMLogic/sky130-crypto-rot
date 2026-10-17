"""cocotb test for flow/smoke/adder.v: directed corners plus seeded random."""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


async def _check(dut, a, b):
    dut.a.value = a
    dut.b.value = b
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")  # let the registered output settle
    assert dut.sum.value.to_unsigned() == a + b, f"{a} + {b} -> {dut.sum.value}"


@cocotb.test()
async def test_directed(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    for a, b in [(0, 0), (1, 1), (255, 0), (255, 1), (255, 255), (128, 128)]:
        await _check(dut, a, b)


@cocotb.test()
async def test_random(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    rng = random.Random(20261017)
    for _ in range(200):
        await _check(dut, rng.randrange(256), rng.randrange(256))
