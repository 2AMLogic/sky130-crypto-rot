"""cocotb bench for rtl/aes/aes_core.v.

One DUT instance. Scores the RTL against the FIPS 197 Appendix B and C.1
vectors and the SP 800-38A F.1.1/F.1.2 ECB-AES128 vectors (provenance sidecars
checked), then against verification/model/aes.py on random keys and blocks, in
both directions. Latency is measured here, in clock cycles.

Latency definition: edge 0 is the rising edge that accepts `start`; latency is
the number of rising edges from edge 0 through the edge after which `done` is
observed high (sampled on the following falling edge), i.e. 11 for encrypt and
21 for decrypt (decision record 0004).
"""

import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from verification.model import aes as model  # noqa: E402
from verification.model import vectorlib  # noqa: E402

ENC_LATENCY = 11
DEC_LATENCY = 21


class Dut:
    def __init__(self, dut):
        self.dut = dut

    async def idle(self):
        d = self.dut
        d.start.value = 0
        d.decrypt.value = 0
        d.block_in.value = 0
        d.key_in.value = 0
        d.zeroize.value = 1
        await RisingEdge(d.clk)
        await FallingEdge(d.clk)
        d.zeroize.value = 0

    async def zeroize(self):
        d = self.dut
        d.zeroize.value = 1
        await RisingEdge(d.clk)
        await FallingEdge(d.clk)
        d.zeroize.value = 0

    async def begin(self, key, block, decrypt):
        """Drive start on the falling edge; return after edge 0 (the accepting edge)."""
        d = self.dut
        await FallingEdge(d.clk)
        d.start.value = 1
        d.decrypt.value = int(decrypt)
        d.block_in.value = int.from_bytes(block, "big")
        d.key_in.value = int.from_bytes(key, "big")
        await RisingEdge(d.clk)  # edge 0
        await FallingEdge(d.clk)
        d.start.value = 0
        d.key_in.value = 0  # the key is sampled at start only

    async def run(self, key, block, decrypt, poke=None):
        """Run one block; return (latency in edges, result bytes)."""
        d = self.dut
        await self.begin(key, block, decrypt)
        lat = 1
        while not int(d.done.value):
            if poke is not None:
                await poke(lat)
            await RisingEdge(d.clk)
            await FallingEdge(d.clk)
            lat += 1
            assert lat <= 64, "done never rose"
        assert not int(d.busy.value), "busy still high with done"
        return lat, int(d.block_out.value).to_bytes(16, "big")


@cocotb.test()
async def test_aes_core(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    bench = Dut(dut)
    await bench.idle()
    first_fail = None
    ran = 0
    lats = {"enc": set(), "dec": set()}

    def fail(msg):
        nonlocal first_fail
        if first_fail is None:
            first_fail = msg

    async def check(label, key, src, decrypt, want):
        nonlocal ran
        lat, got = await bench.run(key, src, decrypt)
        ran += 1
        what = "decrypt" if decrypt else "encrypt"
        lats["dec" if decrypt else "enc"].add(lat)
        if got != want:
            fail(f"{label} {what}: got {got.hex()} expected {want.hex()}")
        elif lat != (DEC_LATENCY if decrypt else ENC_LATENCY):
            fail(f"{label} {what}: latency {lat}")

    async def both(label, key, pt, ct):
        await check(label, key, pt, False, ct)
        await check(label, key, ct, True, pt)

    # published vectors
    for name in ("fips197.txt", "sp800-38a-ecb.txt"):
        vectors = vectorlib.parse_fips197(vectorlib.check_provenance(name))
        assert len(vectors) == vectorlib.count_fips197_records(vectorlib.VECTOR_DIR / name)
        for section, v in vectors:
            await both(f"{name}[{section}]", v["KEY"], v["PLAINTEXT"], v["CIPHERTEXT"])

    # random cross-check against the golden model, key changing every block
    rng = random.Random(1)
    for i in range(100):
        key = bytes(rng.getrandbits(8) for _ in range(16))
        pt = bytes(rng.getrandbits(8) for _ in range(16))
        await both(f"random[{i}]", key, pt, model.encrypt_block(key, pt))

    # start while busy is ignored: the in-flight block completes unchanged
    key, pt = bytes(range(16)), bytes(range(16, 32))

    async def poke_start(lat):
        # a decrypt start with other data and key, held for one edge mid-block
        if lat == 3:
            dut.start.value = 1
            dut.decrypt.value = 1
            dut.block_in.value = 0xDEADBEEF
            dut.key_in.value = 0xFEED
        elif lat == 4:
            dut.start.value = 0
            dut.key_in.value = 0

    lat, got = await bench.run(key, pt, False, poke=poke_start)
    ran += 1
    if got != model.encrypt_block(key, pt) or lat != ENC_LATENCY:
        fail(f"start-while-busy: got {got.hex()} latency {lat}")

    # block_out reads zero while a block is in flight
    await bench.begin(key, pt, False)
    if int(dut.block_out.value) != 0 or not int(dut.busy.value):
        fail("block_out not zero while busy")
    while not int(dut.done.value):
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)

    # zeroize mid-block: key and state registers clear, no result, no residue
    for decrypt in (False, True):
        key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
        pt = bytes.fromhex("3243f6a8885a308d313198a2e0370734")
        await bench.begin(key, pt, decrypt)
        for _ in range(4):
            await RisingEdge(dut.clk)
            await FallingEdge(dut.clk)
        await bench.zeroize()
        regs = (int(dut.state_q.value), int(dut.rk_q.value), int(dut.rnd_q.value))
        if regs != (0, 0, 0) or int(dut.busy.value) or int(dut.done.value) or int(dut.block_out.value):
            fail(f"zeroize mid-block (decrypt={decrypt}): registers {regs}")
        for _ in range(30):  # nothing completes afterwards
            await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        if int(dut.done.value) or int(dut.block_out.value):
            fail("result appeared after zeroize")
        # the core is usable again and carries nothing over from the old key
        await check("after-zeroize", bytes(range(16)), bytes.fromhex("00112233445566778899aabbccddeeff"),
                    False, bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a"))

    # the round-key register is clear once a block completes; zeroize clears a held result
    await bench.run(key, pt, False)
    if int(dut.rk_q.value) != 0:
        fail("rk_q not cleared at completion")
    await bench.zeroize()
    if int(dut.done.value) or int(dut.state_q.value) != 0:
        fail("zeroize after done left state or done set")

    dut._log.info(
        f"SUMMARY vectors={ran} first_failure={first_fail} "
        f"latency: encrypt {sorted(lats['enc'])} decrypt {sorted(lats['dec'])} cycles"
    )
    assert first_fail is None, f"first failing vector: {first_fail}"
