"""cocotb bench for rtl/sha256/sha256_core.v.

One DUT instance, no reset between messages (back-to-back). Scores the RTL
against the CAVP digests in the .rsp files, against verification/model/sha256.py
(for the lengths the .rsp files lack), and against fixed independent digests
(the same table test_sha256_padding.py uses, plus FIPS 180-4 `abc` and the
119-byte case). Latency is measured here, in clock cycles.

Latency definition: edge 0 is the rising edge on which the transfer that
completes a block is accepted; latency is the number of rising edges from
there until digest_valid is observed high, i.e. 65 per block hashed.
"""

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from verification.model import sha256 as model_sha256  # noqa: E402
from verification.model import vectorlib  # noqa: E402

CYCLES_PER_BLOCK = 65

# Digests computed once with an independent implementation (hashlib), not the model.
INDEPENDENT = {
    b"": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    b"abc": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    b"a" * 55: "9f4390f8d30c2dd92ec9f095b65e2b9ae9b0a925a5258e241c9f1e910f734318",
    b"a" * 56: "b35439a4ac6f0948b6d6f9e3c6af0f5f590ce20f1bde7090ef7970686ec6738a",
    b"a" * 63: "7d3e74a05d7db15bce4ad9ec0658ea98e3f06eeecf16b4c6fff2da457ddc2f34",
    b"a" * 64: "ffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb",
    b"a" * 119: "31eba51c313a5c08226adf18d4a359cfdfd8d2e816b13f4af952f7ea6584dcfb",
    b"a" * 1_000_000: "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0",
}


def n_blocks(nbytes):
    """Blocks the core hashes for an nbytes message (padding included)."""
    return (nbytes + 8) // 64 + 1


class Dut:
    def __init__(self, dut):
        self.dut = dut

    async def reset(self):
        d = self.dut
        d.rst_n.value = 0
        d.scrub.value = 0
        d.in_valid.value = 0
        d.in_data.value = 0
        d.in_last.value = 0
        d.in_empty.value = 0
        await ClockCycles(d.clk, 3)
        await FallingEdge(d.clk)
        d.rst_n.value = 1
        await RisingEdge(d.clk)

    async def send(self, msg):
        """Stream msg; return (cycles from the final accept edge to digest_valid, digest).

        Every transfer is driven on the falling edge and accepted at the next
        rising edge when in_ready is high. The message is ended with in_last on
        its final byte, or with a data-less in_last (in_empty) if it is empty.
        """
        d = self.dut
        data = list(msg) if msg else [None]
        for i, byte in enumerate(data):
            last = i == len(data) - 1
            await FallingEdge(d.clk)
            d.in_valid.value = 1
            d.in_data.value = 0 if byte is None else byte
            d.in_last.value = int(last)
            d.in_empty.value = int(byte is None)
            while True:
                await RisingEdge(d.clk)  # in_ready as it was before this edge
                if int(d.in_ready.value):
                    break
            # this edge accepted the transfer (edge 0 for the last one)
        await FallingEdge(d.clk)
        d.in_valid.value = 0
        d.in_last.value = 0
        d.in_empty.value = 0
        cycles = 0
        # digest_valid is sampled on the falling edge after each rising edge
        while not int(d.digest_valid.value):
            await RisingEdge(d.clk)
            await FallingEdge(d.clk)
            cycles += 1
            assert cycles <= 4 * CYCLES_PER_BLOCK + 8, "digest_valid never rose"
        # digest_valid is sampled half a cycle after its rising edge; the first
        # sample is edge 0's falling edge (cycles == 0) and each loop pass is one edge
        return cycles, int(d.digest.value).to_bytes(32, "big")


def check(label, got, want):
    assert got == want, f"{label}: digest {got.hex()} != expected {want.hex()}"


@cocotb.test()
async def test_sha256_core(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    bench = Dut(dut)
    await bench.reset()
    ran = 0
    first_fail = None
    lat = {}

    async def run(label, msg, want):
        nonlocal ran, first_fail
        cycles, got = await bench.send(msg)
        ran += 1
        ok = got == want
        # the last accepted transfer is edge 0; blocks left to hash after it:
        left = n_blocks(len(msg)) - (len(msg) - 1) // 64 if msg else 1
        if ok and cycles != CYCLES_PER_BLOCK * left:
            ok = False
            label += f" (latency {cycles} != {CYCLES_PER_BLOCK * left})"
        if not ok and first_fail is None:
            first_fail = f"{label}: digest {got.hex()} expected {want.hex()}"
        lat.setdefault(left, set()).add(cycles)

    # independent fixed digests (not the model): empty, abc, boundary lengths, 119
    for msg, hexd in INDEPENDENT.items():
        if len(msg) >= 1_000_000:
            continue
        await run(f"fixed len={8 * len(msg)}", msg, bytes.fromhex(hexd))
        check(f"model len={8 * len(msg)}", model_sha256(msg), bytes.fromhex(hexd))

    # the same lengths against the model, plus neighbours around block edges
    for n in sorted({0, 1, 54, 55, 56, 57, 63, 64, 65, 118, 119, 120, 127, 128, 129}):
        msg = bytes((7 * i + n) & 0xFF for i in range(n))
        await run(f"model len={8 * n}", msg, model_sha256(msg))

    # CAVP vectors from the published .rsp files, one DUT instance, no reset
    for name in ("SHA256ShortMsg.rsp", "SHA256LongMsg.rsp"):
        vectors = vectorlib.parse_cavp_sha(vectorlib.check_provenance(name))
        assert len(vectors) == vectorlib.count_cavp_records(vectorlib.VECTOR_DIR / name)
        for idx, (msg, md) in enumerate(vectors):
            await run(f"{name}[{idx}] Len={8 * len(msg)}", msg, md)

    summary = ", ".join(
        f"{k} block(s) after last accept: {sorted(v)} cycles" for k, v in sorted(lat.items())
    )
    dut._log.info(f"SUMMARY vectors={ran} first_failure={first_fail} latency: {summary}")
    if 1 in lat and lat[1] == {CYCLES_PER_BLOCK}:
        dut._log.info("65 cycles per block")
    assert first_fail is None, f"first failing vector: {first_fail}"


@cocotb.test()
async def test_million_a(dut):
    """FIPS 180-4 million-`a` KAT. About 2M cycles; selected by sim-million-a-request.json only."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    bench = Dut(dut)
    await bench.reset()
    cycles, got = await bench.send(b"a" * 1_000_000)
    check("million-a", got, bytes.fromhex(INDEPENDENT[b"a" * 1_000_000]))
    # 1_000_000 is a multiple of 64: the last byte completes a block and the
    # padding block follows, so two blocks are hashed after the last accept.
    assert cycles == 2 * CYCLES_PER_BLOCK, f"latency {cycles}"
    dut._log.info("million-a: digest matches, 130 cycles after the last accept (2 blocks)")


SCRUBBED = ("w", "hh", "a", "b", "c", "d", "e", "f", "g", "h", "len", "t", "dvalid")


def dirty(dut):
    """Names of the scrubbed registers that are not all-zero (hierarchical read)."""
    return [n for n in SCRUBBED if int(getattr(dut, n).value) != 0]


async def pulse_scrub(dut):
    """Assert scrub for exactly one rising edge; return after the next falling edge."""
    await FallingEdge(dut.clk)
    dut.scrub.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.scrub.value = 0


async def feed(dut, msg, nbytes):
    """Accept the first nbytes of msg (no in_last), driving on falling edges."""
    for byte in msg[:nbytes]:
        await FallingEdge(dut.clk)
        dut.in_valid.value = 1
        dut.in_data.value = byte
        dut.in_last.value = 0
        dut.in_empty.value = 0
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.in_valid.value = 0


@cocotb.test()
async def test_scrub(dut):
    """scrub zeroes w/hh/a..h (and control) from any state; later messages still hash right."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    bench = Dut(dut)
    await bench.reset()
    failures = []

    def expect_clean(label):
        bad = dirty(dut)
        if bad:
            failures.append(f"{label}: not zero after scrub: {bad}")

    follow = bytes((3 * i + 1) & 0xFF for i in range(100))

    async def check_follow(label):
        _, got = await bench.send(follow)
        if got != model_sha256(follow):
            failures.append(f"{label}: next message digest {got.hex()} != model")

    # 1. idle, after a finished message (H and block buffer hold its state)
    await bench.send(b"abc")
    assert dirty(dut), "bench premise: registers should hold state after a message"
    await pulse_scrub(dut)
    expect_clean("idle after message")
    if int(dut.digest_valid.value):
        failures.append("idle after message: digest_valid still high")
    await check_follow("idle")

    # 2. mid-block collect (partial block buffer)
    await feed(dut, bytes(range(1, 40)), 39)
    assert int(dut.w.value) != 0
    await pulse_scrub(dut)
    expect_clean("mid-collect")
    await check_follow("mid-collect")

    # 3. mid-block rounds, at several round indices, plus the add edge
    for rounds in (1, 17, 40, 64, 65):
        await feed(dut, bytes(range(64)), 64)  # 64th byte commits the block
        await ClockCycles(dut.clk, rounds - 1)
        await FallingEdge(dut.clk)
        assert int(dut.in_ready.value) == 0, "bench premise: block should be hashing"
        await pulse_scrub(dut)
        expect_clean(f"mid-rounds (edge {rounds})")
        if not int(dut.in_ready.value):
            failures.append(f"mid-rounds (edge {rounds}): not back in collect")
        await check_follow(f"mid-rounds {rounds}")

    # 4. during the length-only spill block (56-byte message: padding spills)
    msg = bytes(range(56))
    await feed(dut, msg, 55)
    await FallingEdge(dut.clk)
    dut.in_valid.value = 1
    dut.in_data.value = msg[55]
    dut.in_last.value = 1
    dut.in_empty.value = 0
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.in_valid.value = 0
    dut.in_last.value = 0
    await ClockCycles(dut.clk, 65 + 20)  # first block done, spill block in rounds
    await FallingEdge(dut.clk)
    assert not int(dut.digest_valid.value), "bench premise: spill block still hashing"
    await pulse_scrub(dut)
    expect_clean("spill block")
    await check_follow("spill")

    # 5. scrub on the cycle accept is high: the transfer must not be taken
    await FallingEdge(dut.clk)
    dut.scrub.value = 1
    dut.in_valid.value = 1
    dut.in_data.value = 0xA5
    dut.in_last.value = 0
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.scrub.value = 0
    dut.in_valid.value = 0
    expect_clean("scrub with accept high")
    await check_follow("accept-high")

    # 6. scrub back to back with a new message, and the whole-message KAT after
    await feed(dut, bytes(range(10)), 10)
    await pulse_scrub(dut)
    await pulse_scrub(dut)
    expect_clean("back-to-back scrubs")
    _, got = await bench.send(b"abc")
    check("abc after scrub", got, bytes.fromhex(INDEPENDENT[b"abc"]))

    dut._log.info(f"SCRUB first_failure={failures[0] if failures else None}")
    assert not failures, f"first failing scrub check: {failures[0]}"
