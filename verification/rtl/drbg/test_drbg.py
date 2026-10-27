"""cocotb bench for rtl/drbg/ctr_drbg.v (inside verification/rtl/drbg/tb_drbg.v).

Two elaborations, chosen by the sim request (see run.sh):

* default -- the shipped 16/8-word seed widths (256-bit entropy + 256-bit
  nonce, 256-bit reseed), reseed interval 5. Scored against
  verification/model/ctr_drbg.py (CtrDrbg, AES-128, df) on directed and seeded
  random 64-byte seeds: instantiate, reseed, generate of every size, Update
  after every request, reseed counter, the error statuses, zeroize.
* DRBG_CAVP -- 6/4 words (24-byte entropy||nonce, 16-byte reseed). Replays the
  AES-128 use-df section of CTR_DRBG_pr_false.rsp whose personalization and
  additional-input lengths are 0 (the only records inside the hardware's
  feature set): instantiate, reseed, generate-and-discard, generate, compare
  the second ReturnedBits.

Which vectors ran on which elaboration is printed in the SUMMARY line.
"""

import os
import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from verification.model import vectorlib  # noqa: E402
from verification.model.ctr_drbg import CtrDrbg  # noqa: E402

CAVP = os.environ.get("DRBG_BENCH_MODE") == "cavp"
INTERVAL = 65536 if CAVP else 5
INST_WORDS, RSD_WORDS = (6, 4) if CAVP else (16, 8)


def seed_int(data):
    """Pack bytes into the seed port: word i at [32i+:32], byte 0 of each word MSB first."""
    assert len(data) % 4 == 0
    v = 0
    for i in range(0, len(data), 4):
        v |= int.from_bytes(data[i:i + 4], "big") << (8 * i)
    return v


class Bench:
    def __init__(self, dut):
        self.d = dut
        self.blocks = []
        self.fails = []

    def fail(self, msg):
        self.fails.append(msg)

    async def reset(self):
        d = self.d
        d.cmd_inst.value = d.cmd_reseed.value = d.cmd_gen.value = 0
        d.gen_bits.value = 0
        d.seed.value = 0
        d.zeroize.value = 1
        await RisingEdge(d.clk)
        await FallingEdge(d.clk)
        d.zeroize.value = 0

    async def command(self, name, *, bits=0, seed=None, limit=4000):
        """Pulse one command; return (err, blocks list of (data,last)). Fails on timeout."""
        d = self.d
        if seed is not None:
            d.seed.value = seed
        d.gen_bits.value = bits
        getattr(d, name).value = 1
        await RisingEdge(d.clk)
        await FallingEdge(d.clk)
        getattr(d, name).value = 0
        blocks = []
        for _ in range(limit):
            if int(d.blk_valid.value):
                blocks.append((int(d.blk_data.value).to_bytes(16, "big"), int(d.blk_last.value)))
            if int(d.done.value):
                return int(d.err.value), blocks
            await RisingEdge(d.clk)
            await FallingEdge(d.clk)
        raise AssertionError(f"{name}: no done within {limit} cycles")


def join(blocks, bits):
    return b"".join(b for b, _ in blocks)[:(bits + 7) // 8]


async def run_shipped(b, rng):
    m = CtrDrbg(use_df=True, key_bits=128, reseed_interval=INTERVAL)

    # generate before instantiate: error status, no data
    err, blocks = await b.command("cmd_gen", bits=128)
    if err != 1 or blocks:
        b.fail(f"generate before instantiate: err={err} blocks={len(blocks)}")
    err, blocks = await b.command("cmd_reseed", seed=0)
    if err != 1:
        b.fail(f"reseed before instantiate: err={err}")

    for rnd in range(6):
        if rnd == 0:
            seed = bytes(range(64))          # directed
        elif rnd == 1:
            seed = bytes(64)
        elif rnd == 2:
            seed = b"\xff" * 64
        else:
            seed = bytes(rng.getrandbits(8) for _ in range(64))
        m.instantiate(seed[:32], seed[32:])
        err, _ = await b.command("cmd_inst", seed=seed_int(seed))
        if err != 0 or int(b.d.seeded.value) != 1:
            b.fail(f"instantiate {rnd}: err={err}")
        sizes = [128, 1024, 8, 129, 256, 1][: INTERVAL]
        for n, bits in enumerate(sizes):
            err, blocks = await b.command("cmd_gen", bits=bits)
            want = m.generate((bits + 7) // 8)
            got = join(blocks, bits)
            nblk = (bits + 127) // 128
            if err != 0 or got != want[: len(got)] or len(blocks) != nblk or [l for _, l in blocks] != [0] * (nblk - 1) + [1]:
                b.fail(f"inst{rnd} gen{n} bits={bits}: err={err} got={got.hex()} want={want.hex()} nblk={len(blocks)}")
            elif bits % 8 == 0 and got != want:
                b.fail(f"inst{rnd} gen{n}: mismatch")
            if n == 4 and not int(b.d.reseed_required.value):
                pass
        # counter: 5 requests already done (interval 5) => next is refused
        err, blocks = await b.command("cmd_gen", bits=128)
        if INTERVAL <= len(sizes):
            if err != 2 or blocks or not int(b.d.reseed_required.value):
                b.fail(f"inst{rnd}: expected RESEED_REQUIRED, err={err} blocks={len(blocks)}")
        # reseed, then generate again
        rs = bytes(rng.getrandbits(8) for _ in range(32))
        m.reseed(rs)
        err, _ = await b.command("cmd_reseed", seed=seed_int(rs))
        if err != 0 or int(b.d.reseed_required.value):
            b.fail(f"reseed {rnd}: err={err}")
        err, blocks = await b.command("cmd_gen", bits=512)
        want = m.generate(64)
        if err != 0 or join(blocks, 512) != want:
            b.fail(f"post-reseed gen {rnd}: err={err}")
        # size errors leave the state and counter untouched (checked by the next generate)
        for bad in (0, 1025, 2047):
            err, blocks = await b.command("cmd_gen", bits=bad)
            if err != 3 or blocks:
                b.fail(f"bad size {bad}: err={err}")
        err, blocks = await b.command("cmd_gen", bits=128)
        want = m.generate(16)
        if err != 0 or join(blocks, 128) != want:
            b.fail(f"gen after size errors {rnd}: err={err}")
        # back-to-back generates: counter at interval-1 / interval
        while m.reseed_counter <= INTERVAL:
            bits = rng.choice([128, 640])
            err, blocks = await b.command("cmd_gen", bits=bits)
            want = m.generate(bits // 8)
            if err != 0 or join(blocks, bits) != want:
                b.fail(f"b2b gen counter={m.reseed_counter}: err={err}")
        err, blocks = await b.command("cmd_gen", bits=128)
        if err != 2 or blocks:
            b.fail(f"counter at interval: err={err}")

    # zeroize clears state: generate is refused as not instantiated
    await b.reset()
    err, blocks = await b.command("cmd_gen", bits=128)
    if err != 1 or blocks or int(b.d.seeded.value):
        b.fail(f"after zeroize: err={err}")
    return 6


async def run_cavp(b):
    path = vectorlib.check_provenance("CTR_DRBG_pr_false.rsp")
    records = vectorlib.parse_cavp_drbg(path)
    assert len(records) == vectorlib.count_cavp_drbg_records(path)
    sel = [r for r in records if r["section"] == "AES-128 use df"
           and len(r["PersonalizationString"]) == 0
           and not any(r["additional"]) and not r["AdditionalInputReseed"]]
    assert sel, "no AES-128 use df records with both lengths 0"
    ran = 0
    for i, r in enumerate(sel):
        assert len(r["EntropyInput"]) + len(r["Nonce"]) == 4 * INST_WORDS
        assert len(r["EntropyInputReseed"]) == 4 * RSD_WORDS and len(r["ReturnedBits"]) == 64
        err, _ = await b.command("cmd_inst", seed=seed_int(r["EntropyInput"] + r["Nonce"]))
        if err:
            b.fail(f"cavp[{i}] inst err={err}")
        err, _ = await b.command("cmd_reseed", seed=seed_int(r["EntropyInputReseed"]))
        if err:
            b.fail(f"cavp[{i}] reseed err={err}")
        await b.command("cmd_gen", bits=512)           # generate and discard
        err, blocks = await b.command("cmd_gen", bits=512)
        got = join(blocks, 512)
        if err or got != r["ReturnedBits"]:
            b.fail(f"cavp[{i}]: err={err} got={got.hex()} want={r['ReturnedBits'].hex()}")
        ran += 1
    return ran


@cocotb.test()
async def test_drbg(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    b = Bench(dut)
    await b.reset()
    if CAVP:
        ran = await run_cavp(b)
        what = f"cavp_aes128_use_df_len0_records={ran} elaboration=6/4words"
    else:
        ran = await run_shipped(b, random.Random(1))
        what = f"model_crosscheck_seeds={ran} elaboration=16/8words interval={INTERVAL}"
    dut._log.info(f"SUMMARY {what} first_failure={b.fails[0] if b.fails else None} failures={len(b.fails)}")
    assert not b.fails, b.fails[0]
