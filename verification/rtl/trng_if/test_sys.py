"""cocotb system bench: drbg_top (trng_if + ctr_drbg + aes_core) in tb_sys.v.

test_sys       -- sibling pins driven by the port-protocol stub (trngmodel.py),
                  reseed interval 3. Instantiate and reseed from collected
                  words, outputs checked against verification/model/ctr_drbg.py
                  with the words the stub saw popped; gated stalls reseeding and
                  an exhausted interval refuses generate (also while gated); an
                  alarm during a running generate stops the output stream,
                  zeroizes Key/V and the seed buffer within the bound and
                  leaves the DRBG unseeded until re-instantiated.
test_sys_real  -- REAL_TRNG: the pinned sibling RTL (fetched by fetch_trng.sh)
                  with shortened start-up/conditioner parameters; the same
                  instantiate/generate/model check on its conditioned words, a
                  health-test alarm forced through the raw tap, the recovery
                  sequence against the real register map, and re-instantiation.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verification.model.ctr_drbg import CtrDrbg  # noqa: E402
from trngmodel import TrngStub, bit  # noqa: E402

INTERVAL = 3
ZERO_BOUND = 6          # cycles from the alarm pin to Key/V zero (2 sync + 1 reg + 1 clear + margin)


def words_to_bytes(ws):
    return b"".join(w.to_bytes(4, "big") for w in ws)


async def cycles(d, n):
    for _ in range(n):
        await FallingEdge(d.clk)


class Sys:
    def __init__(self, dut, ratio=40, real=False):
        self.d = dut
        self.fails = []
        self.real = real
        self.pops = []                       # words popped from the sibling, in order
        self.stub = None if real else TrngStub(dut, ratio)
        self.blocks = []
        self.done_seen = 0
        self.interval = 65536 if real else INTERVAL
        self.model = CtrDrbg(use_df=True, key_bits=128, reseed_interval=self.interval)

    def check(self, cond, msg):
        if not cond:
            self.fails.append(msg)

    def secrets(self):
        u = self.d.u.u_drbg
        return {n: int(getattr(u, n).value) if getattr(u, n).value.is_resolvable else -1
                for n in ("key_q", "v_q", "chain_q", "tk_q", "tx_q", "t0_q", "prov_q", "bd_q")}

    def seed_zero(self):
        v = self.d.u.u_if.seed_q.value
        return v.is_resolvable and int(v) == 0

    async def monitor(self):
        d = self.d
        while True:
            await RisingEdge(d.clk)
            if bit(d.blk_valid):
                self.blocks.append((bit(d.blk_data), bit(d.blk_last)))
            if bit(d.done):
                self.done_seen += 1

    async def sample_pops(self):
        """Real-sibling mode: record each word moved at a sample-clock rising edge."""
        d = self.d
        while True:
            await RisingEdge(d.trng_clk)
            if bit(d.trng_out_ready) and bit(d.trng_out_valid) and bit(d.rst_n):
                self.pops.append(bit(d.trng_out_data))

    async def boot(self):
        d = self.d
        d.req_inst.value = d.req_reseed.value = d.req_gen.value = 0
        d.gen_bits.value = 0
        d.sw_zeroize.value = 0
        d.rst_n.value = 0
        cocotb.start_soon(self.monitor())
        if self.real:
            d.raw_valid.value = 1
            d.raw_bit.value = 0
            cocotb.start_soon(self.trng_clock())
            cocotb.start_soon(self.sample_pops())
            cocotb.start_soon(self.raw_source())
        else:
            self.stub.start()
        await cycles(d, 6)
        d.rst_n.value = 1

    async def trng_clock(self):
        """Sample clock for the real sibling: 40 core cycles + 3 ns, 7 ns phase."""
        from cocotb.triggers import Timer
        d = self.d
        d.trng_clk.value = 0
        await Timer(7, unit="ns")
        while True:
            d.trng_clk.value = 1
            await Timer(401, unit="ns")
            d.trng_clk.value = 0
            await Timer(402, unit="ns")

    async def raw_source(self):
        """Raw tap: pseudo-random bits, or a stuck value while self.stuck is set."""
        d = self.d
        rng = random.Random(7)
        self.stuck = None
        while True:
            await RisingEdge(d.trng_clk)
            d.raw_bit.value = rng.getrandbits(1) if self.stuck is None else self.stuck

    def pulse_cmd(self, name, bits=0):
        async def go():
            d = self.d
            await cycles(d, 1)
            d.gen_bits.value = bits
            getattr(d, name).value = 1
            await cycles(d, 1)
            getattr(d, name).value = 0
        return go()

    async def run_cmd(self, name, bits=0, limit=2_000_000):
        """Issue a request; return (err, blocks) when done pulses. Raises on timeout."""
        d = self.d
        n_done, n_blk = self.done_seen, len(self.blocks)
        await self.pulse_cmd(name, bits)
        for _ in range(limit):
            if self.done_seen > n_done:
                return int(d.err.value), self.blocks[n_blk:]
            await cycles(d, 1)
        raise AssertionError(f"{name}: no done")

    async def wait_ready(self):
        """Wait for the sibling to be ungated/started (stub or real)."""
        d = self.d
        for _ in range(2_000_000):
            if bit(d.trng_startup_done) and not bit(d.trng_gated) and bit(d.rst_n):
                return
            await cycles(d, 1)
        raise AssertionError("sibling never became ready")


def blocks_bytes(blocks, bits):
    return b"".join(w.to_bytes(16, "big") for w, _ in blocks)[:(bits + 7) // 8]


async def instantiate(s):
    n0 = len(s.stub.pops) if not s.real else len(s.pops)
    err, _ = await s.run_cmd("req_inst")
    pops = [w for _, _, w in s.stub.pops[n0:]] if not s.real else s.pops[n0:]
    return err, pops


async def basic(s):
    d = s.d
    await s.wait_ready()
    # instantiate from collected words, then generate sizes against the model
    err, pops = await instantiate(s)
    s.check(err == 0 and len(pops) == 16 and bit(d.seeded), f"instantiate: err={err} pops={len(pops)}")
    seed = words_to_bytes(pops)
    s.model.instantiate(seed[:32], seed[32:])
    s.check(s.seed_zero(), "seed buffer cleared after instantiate")
    for bits in (128, 1024, 8 * 5):
        err, blocks = await s.run_cmd("req_gen", bits)
        want = s.model.generate((bits + 7) // 8)
        s.check(err == 0 and blocks_bytes(blocks, bits) == want, f"generate {bits}: err={err}")
    # reseed from 8 fresh words
    n0 = len(s.stub.pops) if not s.real else len(s.pops)
    err, _ = await s.run_cmd("req_reseed")
    pops = [w for _, _, w in s.stub.pops[n0:]] if not s.real else s.pops[n0:]
    s.check(err == 0 and len(pops) == 8, f"reseed: err={err} pops={len(pops)}")
    s.model.reseed(words_to_bytes(pops))
    err, blocks = await s.run_cmd("req_gen", 256)
    s.check(err == 0 and blocks_bytes(blocks, 256) == s.model.generate(32), "generate after reseed")


@cocotb.test()
async def test_sys(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    s = Sys(dut, ratio=40)
    stub, d = s.stub, dut
    await s.boot()
    await basic(s)

    # -- interval: the 3rd request after a seed is the last; the 4th is refused ----
    # (basic() already made 3 requests after instantiate and 1 after reseed)
    for _ in range(INTERVAL - 1):
        err, blocks = await s.run_cmd("req_gen", 128)
        s.check(err == 0 and blocks_bytes(blocks, 128) == s.model.generate(16), "generate before interval")
    err, blocks = await s.run_cmd("req_gen", 128)
    s.check(err == 2 and not blocks and bit(d.reseed_required), f"interval reached: err={err} blocks={len(blocks)}")
    # gated while RESEED_REQUIRED: generate still refused; reseed stalls until ungated
    stub.gated_force = 1
    await stub.next_edge(3)
    err, blocks = await s.run_cmd("req_gen", 128)
    s.check(err == 2 and not blocks, "reseed required and gated: generate refused")
    n0 = len(stub.pops)
    n_done = s.done_seen
    await s.pulse_cmd("req_reseed")
    await stub.next_edge(12)
    s.check(s.done_seen == n_done and len(stub.pops) == n0 and bit(d.busy), "reseed stalls while gated")
    stub.gated_force = 0
    for _ in range(100000):
        if s.done_seen > n_done:
            break
        await cycles(d, 1)
    pops = [w for _, _, w in stub.pops[n0:]]
    s.check(len(pops) == 8 and not bit(d.reseed_required), "reseed completes after ungating with 8 clean words")
    s.model.reseed(words_to_bytes(pops))
    err, blocks = await s.run_cmd("req_gen", 128)
    s.check(err == 0 and blocks_bytes(blocks, 128) == s.model.generate(16), "generate after clean reseed")

    # -- alarm during a running generate ----------------------------------------
    n_done, n_blk = s.done_seen, len(s.blocks)
    await s.pulse_cmd("req_gen", 1024)
    for _ in range(60):                                   # let a few blocks stream
        await cycles(d, 1)
    s.check(bit(d.busy) and len(s.blocks) > n_blk, "generate running before the alarm")
    stub.raise_alarm()
    await stub.next_edge()
    t_pin = stub.alarm_set_cycle
    z_cycle = None
    for _ in range(40):
        await RisingEdge(d.clk)
        sec = s.secrets()
        if z_cycle is None and all(v == 0 for v in sec.values()) and s.seed_zero():
            z_cycle = stub.cycle
            break
    s.check(z_cycle is not None and z_cycle - t_pin <= ZERO_BOUND,
            f"alarm -> Key/V/working regs/seed zero in {None if z_cycle is None else z_cycle - t_pin} cycles (bound {ZERO_BOUND}): {s.secrets()}")
    nb = len(s.blocks)
    for _ in range(40):                                   # held zero while the alarm is asserted
        await cycles(d, 1)
        s.check(all(v == 0 for v in s.secrets().values()) and s.seed_zero(), "held zero during alarm")
    s.check(len(s.blocks) == nb and s.done_seen == n_done, "no block or done after zeroize")
    s.check(not bit(d.seeded) and not bit(d.busy), "unseeded and idle after alarm")
    await stub.until(lambda: stub.alarm == 0, edges=60)
    await s.wait_ready()
    err, blocks = await s.run_cmd("req_gen", 128)
    s.check(err == 1 and not blocks, f"generate after alarm refused until re-instantiated: err={err}")
    s.model = CtrDrbg(use_df=True, key_bits=128, reseed_interval=INTERVAL)
    err, pops = await instantiate(s)
    seed = words_to_bytes(pops)
    s.model.instantiate(seed[:32], seed[32:])
    err2, blocks = await s.run_cmd("req_gen", 512)
    s.check(err == 0 and err2 == 0 and blocks_bytes(blocks, 512) == s.model.generate(64), "re-instantiate after recovery")
    s.check(not stub.violations, f"stub violations {stub.violations[:2]}")
    first = s.fails[0] if s.fails else None
    dut._log.info(f"SUMMARY sys stub interval={INTERVAL} pops={len(stub.pops)} first_failure={first} failures={len(s.fails)}")
    assert not s.fails, s.fails[0]


@cocotb.test()
async def test_sys_real(dut):
    assert hasattr(dut, "raw_bit"), "test_sys_real needs the REAL_TRNG elaboration"
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    s = Sys(dut, real=True)
    d = dut
    await s.boot()
    await basic(s)
    # health-test alarm through the real raw tap: a stuck source trips the RCT
    n_done = s.done_seen
    s.stuck = 1
    for _ in range(4000000):
        await cycles(d, 1)
        if bit(d.trng_alarm):
            break
    s.check(bit(d.trng_alarm), "real sibling raised its alarm on a stuck raw tap")
    t = 0
    while not (all(v == 0 for v in s.secrets().values()) and s.seed_zero()) and t < 40:
        await cycles(d, 1)
        t += 1
    s.check(t < 40 and not bit(d.seeded), "real alarm zeroized Key/V and the seed buffer")
    s.stuck = None
    for _ in range(4000000):
        await cycles(d, 1)
        if not bit(d.trng_alarm) and bit(d.trng_startup_done) and not bit(d.alarm_zeroized):
            break
    s.check(not bit(d.trng_alarm) and bit(d.trng_startup_done), "real sibling recovered (ALARM W1C, SOFT_RST, enable) and restarted")
    s.model = CtrDrbg(use_df=True, key_bits=128, reseed_interval=65536)
    err, pops = await instantiate(s)
    seed = words_to_bytes(pops)
    s.model.instantiate(seed[:32], seed[32:])
    err2, blocks = await s.run_cmd("req_gen", 512)
    s.check(err == 0 and err2 == 0 and blocks_bytes(blocks, 512) == s.model.generate(64), "re-instantiate from the real sibling after recovery")
    first = s.fails[0] if s.fails else None
    dut._log.info(f"SUMMARY sys real pops={len(s.pops)} first_failure={first} failures={len(s.fails)}")
    assert not s.fails, s.fails[0]
