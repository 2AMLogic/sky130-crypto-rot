"""cocotb bench for rtl/trng_if/trng_if.v (wrapper tb_trng_if.v) against the
port-protocol stub in trngmodel.py.

Covers: reset/bring-up writes (CTRL = 0b011 once, bus_re never), seed
collection of 16 and 8 words with exactly one pop per word, the t_fall gating
rules (gated, one-period gated pulse, startup_done = 0: partial seed discarded
and collection restarts from word 0; no word accepted when gated was high at
the previous or current sample), alarm -> zeroize within the bound, the ALARM
clear only after zeroize, recovery through SOFT_RST and re-enable, software
zeroize. test_trng_if_1000 repeats the collection at the real 1000:1 ratio.
"""

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trngmodel import TrngStub  # noqa: E402

RATIO = 40
CTRL_ADDR, ALARM_ADDR = 0, 4


def seed_words(dut, n):
    v = int(dut.seed.value)
    return [(v >> (32 * i)) & 0xFFFFFFFF for i in range(n)]


async def cycles(d, n):
    for _ in range(n):
        await FallingEdge(d.clk)


def last_pops(stub, n):
    return [w for _, _, w in stub.pops[-n:]]


class Env:
    def __init__(self, dut, ratio=RATIO):
        self.d = dut
        self.fails = []
        self.stub = TrngStub(dut, ratio)

    def check(self, cond, msg):
        if not cond:
            self.fails.append(msg)

    async def boot(self):
        d = self.d
        d.seed_req.value = d.seed_reseed.value = d.seed_release.value = 0
        d.sw_zeroize.value = 0
        d.rst_n.value = 0
        self.stub.start()
        await cycles(d, 6)
        self.check(int(d.trng_rst_n.value) == 0 and int(d.zeroize.value) == 1, "reset: trng_rst_n/zeroize")
        d.rst_n.value = 1
        await self.stub.until(lambda: self.stub.startup_done)
        self.check(int(d.trng_rst_n.value) == 1, "trng_rst_n released")

    async def request(self, reseed):
        d = self.d
        await cycles(d, 1)          # align to a falling edge so the pulse spans one rising edge
        d.seed_reseed.value = int(reseed)
        d.seed_req.value = 1
        await cycles(d, 1)
        d.seed_req.value = 0

    async def collect(self, reseed, n, limit=400):
        await self.request(reseed)
        try:
            await self.stub.until(lambda: int(self.d.seed_ready.value) == 1, edges=limit)
        except AssertionError:
            u = self.d.u
            self.d._log.error(f"collect stuck: collecting={u.collecting_q.value} wcount={u.wcount_q.value} prev_bad={u.prev_bad_q.value} "
                              f"zr={u.zr_q.value} pops={len(self.stub.pops)} startup={self.stub.startup_done} sq={u.sq_q.value} "
                              f"valid={self.d.trng_out_valid.value} gated={self.d.trng_gated.value} ordy={self.d.trng_out_ready.value}")
            raise
        return seed_words(self.d, n)

    async def release(self):
        d = self.d
        await cycles(d, 1)
        d.seed_release.value = 1
        await cycles(d, 1)
        d.seed_release.value = 0
        await cycles(d, 2)


async def collection(env, full):
    stub, d = env.stub, env.d
    await env.boot()
    env.check([w[2:] for w in stub.writes] == [(CTRL_ADDR, 3)], f"bring-up writes: {stub.writes}")

    n0 = len(stub.pops)
    got = await env.collect(False, 16)
    env.check(len(stub.pops) - n0 == 16, f"16-word seed popped {len(stub.pops) - n0} words")
    env.check(got == last_pops(stub, 16), "seed words are the 16 popped words in arrival order")
    await stub.next_edge(6)
    env.check(len(stub.pops) - n0 == 16 and seed_words(d, 16) == got, "seed held, no further pops while ready")
    await env.release()
    env.check(int(d.seed.value) == 0 and int(d.seed_ready.value) == 0, "seed cleared on release")

    n0 = len(stub.pops)
    got = await env.collect(True, 8)
    env.check(len(stub.pops) - n0 == 8 and got == last_pops(stub, 8), "8-word reseed")
    env.check(int(d.seed.value) >> 256 == 0, "reseed fills only 8 words")
    await env.release()
    env.check(not stub.violations, f"protocol violations: {stub.violations[:3]}")
    return env


@cocotb.test()
async def test_trng_if_1000(dut):
    """Collection at the real 1000:1 clock ratio."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    env = Env(dut, 1000)
    await collection(env, False)
    report(dut, env, "trng_if ratio=1000:1 stub (collection only)")


@cocotb.test()
async def test_trng_if(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    env = Env(dut, RATIO)
    stub, d = env.stub, dut
    await collection(env, True)

    # -- gated / startup_done = 0 mid-seed: partial seed discarded, restart at word 0 --
    for label, setter in (("gated", "gated_force"), ("startup_done=0", "startup_force_low")):
        n0 = len(stub.pops)
        await env.request(False)
        await stub.until(lambda: len(stub.pops) - n0 >= 5)
        setattr(stub, setter, 1)
        await stub.next_edge(2)
        env.check(int(d.seed.value) == 0, f"{label}: partial seed discarded")
        await stub.next_edge(3)
        popped_during = len(stub.pops)
        env.check(int(d.seed_ready.value) == 0, f"{label}: not ready while gated")
        setattr(stub, setter, 0)
        await stub.until(lambda: int(d.seed_ready.value) == 1, edges=300)
        env.check(len(stub.pops) - popped_during >= 16, f"{label}: collection restarted from word 0")
        env.check(seed_words(d, 16) == last_pops(stub, 16), f"{label}: seed = the 16 words popped after the gate")
        await env.release()

    # -- one-period gated pulse ---------------------------------------------------
    n0 = len(stub.pops)
    await env.request(False)
    await stub.until(lambda: len(stub.pops) - n0 >= 3)
    await stub.next_edge()
    stub.gated_force = 1
    await stub.next_edge()
    stub.gated_force = 0
    await stub.until(lambda: int(d.seed_ready.value) == 1, edges=300)
    env.check(seed_words(d, 16) == last_pops(stub, 16), "one-period gated pulse: partial seed discarded")
    await env.release()

    # -- alarm: zeroize bound, ALARM write only after zeroize, recovery ---------
    await env.request(False)
    await stub.until(lambda: len(stub.pops) >= 4 and int(d.seed.value) != 0)
    w0 = len(stub.writes)
    stub.raise_alarm()
    await stub.next_edge()                       # pins change just after this edge
    t_pin = stub.alarm_set_cycle
    zr_cycle = None
    for _ in range(30):
        await RisingEdge(d.clk)
        if int(d.zeroize.value):
            zr_cycle = stub.cycle
            break
    env.check(zr_cycle is not None and zr_cycle - t_pin <= 6,
              f"alarm -> zeroize latency {None if zr_cycle is None else zr_cycle - t_pin} cycles (bound 6)")
    await cycles(d, 3)
    env.check(int(d.seed.value) == 0 and int(d.seed_ready.value) == 0, "alarm: seed buffer zero")
    for _ in range(40):                          # held zero while alarm asserted, with a request pending
        d.seed_req.value = 1
        await cycles(d, 1)
        env.check(int(d.seed.value) == 0, "alarm held: seed stays zero")
    d.seed_req.value = 0
    await stub.until(lambda: stub.alarm == 0, edges=50)
    new = stub.writes[w0:]
    env.check(bool(new) and new[0][2:] == (ALARM_ADDR, 7), f"first write after alarm is ALARM W1C: {new}")
    env.check(zr_cycle is not None and new and new[0][1] > zr_cycle + 1, "ALARM written only after zeroize completed")
    await stub.until(lambda: stub.startup_done and stub.enabled, edges=80)
    new = [x[2:] for x in stub.writes[w0:]]
    env.check(new == [(ALARM_ADDR, 7), (CTRL_ADDR, 4), (CTRL_ADDR, 3)], f"recovery sequence: {new}")
    await stub.next_edge(4)
    env.check(int(d.alarm_zeroized.value) == 0, "recovered: alarm_zeroized low")
    await env.release()
    got = await env.collect(False, 16)
    env.check(got == last_pops(stub, 16), "seed collected after recovery")
    d.sw_zeroize.value = 1
    await cycles(d, 3)
    d.sw_zeroize.value = 0
    env.check(int(d.seed.value) == 0 and int(d.seed_ready.value) == 0, "sw_zeroize clears the seed")

    env.check(not stub.violations, f"protocol violations: {stub.violations[:3]}")
    allw = {w[2:] for w in stub.writes}
    env.check(allw <= {(CTRL_ADDR, 3), (CTRL_ADDR, 4), (ALARM_ADDR, 7)}, f"unexpected bus writes {allw}")
    report(dut, env, f"trng_if ratio={RATIO}:1 stub")


def report(dut, env, label):
    first = env.fails[0] if env.fails else None
    dut._log.info(f"SUMMARY {label} pops={len(env.stub.pops)} writes={len(env.stub.writes)} first_failure={first} failures={len(env.fails)}")
    assert not env.fails, env.fails[0]
