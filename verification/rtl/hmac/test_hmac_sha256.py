"""cocotb bench for rtl/hmac/hmac_sha256.v.

One DUT instance, no reset between operations (back-to-back). Scores the RTL
against RFC 4231 test cases 1-4, 6 and 7 (vectors parsed from the provenance-
checked verification/vectors/rfc4231.txt, not retyped) and against
verification/model/hmac_sha256.py for random keys and messages, including
message lengths 0, 55, 56, 63, 64, 119 and key lengths 32, 64, 65. Cases with a
key of at most 32 bytes run through both key ports (slot and byte stream).
RFC 4231 case 5 (truncated output) is NOT APPLICABLE: the core emits the full
32-byte tag only, and the bench says so. The cycle count from the `start` edge
(counted as edge 1) to the first sample with mac_valid high is measured here.
"""

import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from verification.model import hmac_sha256 as model_hmac  # noqa: E402
from verification.model import vectorlib  # noqa: E402

MAX_CYCLES = 20000


class Dut:
    def __init__(self, dut):
        self.dut = dut
        self.edges = 0
        cocotb.start_soon(self._count())

    async def _count(self):
        while True:
            await RisingEdge(self.dut.clk)
            self.edges += 1

    async def reset(self):
        d = self.dut
        d.rst_n.value = 0
        for s in ("clear", "start", "key_long", "key", "key_len", "lk_valid", "lk_data",
                  "lk_last", "lk_empty", "in_valid", "in_data", "in_last", "in_empty"):
            getattr(d, s).value = 0
        await ClockCycles(d.clk, 3)
        await FallingEdge(d.clk)
        d.rst_n.value = 1
        await RisingEdge(d.clk)

    async def _stream(self, prefix, data, rng, gaps):
        """Drive a byte stream; each transfer is held until ready is seen high at a rising edge."""
        d = self.dut
        valid = getattr(d, prefix + "_valid")
        ready = getattr(d, prefix + "_ready")
        items = list(data) if data else [None]
        for i, byte in enumerate(items):
            last = i == len(items) - 1
            if gaps and rng.random() < 0.2:
                await FallingEdge(d.clk)
                valid.value = 0
                await ClockCycles(d.clk, rng.randint(1, 3))
            await FallingEdge(d.clk)
            valid.value = 1
            getattr(d, prefix + "_data").value = 0 if byte is None else byte
            getattr(d, prefix + "_last").value = int(last)
            getattr(d, prefix + "_empty").value = int(byte is None)
            while True:
                await RisingEdge(d.clk)
                if int(ready.value):
                    break
        await FallingEdge(d.clk)
        valid.value = 0
        getattr(d, prefix + "_last").value = 0
        getattr(d, prefix + "_empty").value = 0

    async def start(self, key, long_port):
        d = self.dut
        await FallingEdge(d.clk)
        d.start.value = 1
        d.key_long.value = int(long_port)
        if not long_port:
            d.key.value = int.from_bytes(bytes(key).ljust(32, b"\x00"), "big")
            d.key_len.value = len(key)
        else:
            d.key.value = 0xDEADBEEF  # must be ignored on the stream port
            d.key_len.value = 31
        await RisingEdge(d.clk)  # the edge that samples start
        await FallingEdge(d.clk)
        d.start.value = 0

    async def hmac(self, key, msg, long_port, rng=None, gaps=False):
        """Run one HMAC; return (cycles from the start edge to mac_valid, mac bytes)."""
        d = self.dut
        assert not int(d.busy.value), "busy before start"
        await self.start(key, long_port)
        t0 = self.edges  # edges counted from the one that sampled start (edge 1)
        assert int(d.busy.value) == 1, "busy not high after start"
        assert int(d.mac_valid.value) == 0, "mac_valid not cleared by start"
        assert int(d.mac.value) == 0, "mac not zero while mac_valid is low"
        if long_port:
            await self._stream("lk", key, rng, gaps)
        await self._stream("in", msg, rng, gaps)
        while not int(d.mac_valid.value):
            await RisingEdge(d.clk)
            await FallingEdge(d.clk)
            assert self.edges - t0 <= MAX_CYCLES, "mac_valid never rose"
        cycles = self.edges - t0 + 1
        assert not int(d.busy.value), "busy still high with mac_valid"
        return cycles, int(d.mac.value).to_bytes(32, "big")


@cocotb.test()
async def test_hmac_sha256(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    bench = Dut(dut)
    await bench.reset()
    rng = random.Random(1)
    ran = 0
    first_fail = None

    async def run(label, key, msg, long_port, want=None, gaps=False):
        nonlocal ran, first_fail
        if want is None:
            want = model_hmac(key, msg)
        cycles, got = await bench.hmac(key, msg, long_port, rng, gaps)
        ran += 1
        if got != want and first_fail is None:
            first_fail = (f"{label} (key {len(key)} B via {'stream' if long_port else 'slot'}, "
                          f"msg {len(msg)} B): mac {got.hex()} expected {want.hex()}")
        return cycles

    # RFC 4231 cases 1-4, 6, 7 (case 5 truncates the output: not applicable)
    cases = vectorlib.parse_rfc4231(vectorlib.check_provenance("rfc4231.txt"))
    assert sorted(cases) == [1, 2, 3, 4, 5, 6, 7]
    dut._log.info("RFC 4231 case 5 (128-bit truncation) not applicable: the core emits the full tag")
    for n in (1, 2, 3, 4, 6, 7):
        key, data, tag = cases[n]
        assert len(tag) == 32
        for long_port in ((0, 1) if len(key) <= 32 else (1,)):
            await run(f"RFC4231 case {n}", key, data, long_port, want=tag)

    # required lengths: messages 0,55,56,63,64,119 x keys 32,64,65
    for klen in (32, 64, 65):
        for mlen in (0, 55, 56, 63, 64, 119):
            key, msg = rng.randbytes(klen), rng.randbytes(mlen)
            for long_port in ((0, 1) if klen <= 32 else (1,)):
                await run("fixed length", key, msg, long_port)
    # key edges: empty, 1 byte, block-boundary neighbours, long
    for klen in (0, 1, 31, 33, 63, 100, 128, 129, 200):
        for mlen in (0, 1, 52):
            key, msg = rng.randbytes(klen), rng.randbytes(mlen)
            for long_port in ((0, 1) if klen <= 32 else (1,)):
                await run("key edge", key, msg, long_port)
    # random keys and lengths, with stalls on the input streams
    for _ in range(40):
        klen, mlen = rng.randint(0, 140), rng.randint(0, 200)
        key, msg = rng.randbytes(klen), rng.randbytes(mlen)
        await run("random", key, msg, int(klen > 32 or rng.random() < 0.5), gaps=True)

    # the KDF message shape (decision 0003): 52-byte message, 32-byte slot key
    kdf_cycles = await run("kdf shape", rng.randbytes(32), rng.randbytes(52), 0)

    # clear aborts an operation mid-flight; the next operation is unaffected
    key, msg = rng.randbytes(32), rng.randbytes(100)
    await bench.start(key, 0)
    await ClockCycles(dut.clk, 40)
    await FallingEdge(dut.clk)
    dut.clear.value = 1
    await FallingEdge(dut.clk)
    dut.clear.value = 0
    assert not int(dut.busy.value) and not int(dut.mac_valid.value), "clear did not idle the block"
    await run("after clear", key, msg, 0)

    dut._log.info(f"SUMMARY vectors={ran} first_failure={first_fail} "
                  f"kdf_shape_cycles_start_to_mac_valid={kdf_cycles}")
    assert first_fail is None, f"first failing vector: {first_fail}"
    assert kdf_cycles >= 4 * 65, f"fewer cycles than 4 compressions: {kdf_cycles}"
