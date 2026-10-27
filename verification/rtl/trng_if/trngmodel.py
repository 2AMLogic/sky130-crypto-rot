"""Bench-side behavioural model of the sibling's port protocol (trng-interface.md section 1).

Not the sibling's RTL and not a TRNG model: it drives out_data/out_valid/gated/
startup_done/alarm and implements only what the interface contract says --
pop when out_ready && out_valid at a rising edge of trng_clk, outputs change
only just after a rising edge, ALARM is sticky until a W1C write, CTRL.SOFT_RST
restarts the start-up count. It deliberately does NOT mask out_valid when gated
(the core must qualify it itself).
"""

import cocotb
from cocotb.triggers import Event, RisingEdge, Timer

W1C_ALARM, CTRL = 4, 0


def bit(sig):
    """Integer value of a signal; an unresolved (X/Z) bit reads as 0 (pre-reset only)."""
    v = sig.value
    return int(v) if v.is_resolvable else 0



def word(k):
    return (k * 0x9E3779B1 + 0x01234567) & 0xFFFFFFFF


class TrngStub:
    def __init__(self, dut, ratio, phase_ns=7, startup_periods=6, extra_ns=3):
        self.d = dut
        self.period_ns = ratio * 20 + extra_ns       # not a multiple of the core period
        self.phase_ns = phase_ns
        self.startup_periods = startup_periods
        self.next = 0                  # stream index of the FIFO head
        self.supply = True
        self.gated_force = 0
        self.startup_force_low = 0
        self.alarm = 0
        self.startup_count = 0
        self.enabled = False
        self.edge = -1
        self.bad_hist = []             # bad_hist[e]: gated|~startup|alarm during the period after edge e
        self.pops = []                 # (edge, stream index, word)
        self.writes = []               # (edge, core cycle, addr, data)
        self.violations = []
        self.cycle = 0
        self.edge_event = Event()
        self.alarm_set_cycle = None
        self.alarm_clear_cycle = None
        self.running = True
        self.startup_done = 0

    # -- test-facing controls (take effect at the next rising edge) ----------
    def raise_alarm(self):
        self.alarm = 1
        self.startup_count = 0
        self.startup_done = 0

    @property
    def gated(self):
        return int(bool(self.gated_force or self.alarm or not self.startup_done))

    async def next_edge(self, n=1):
        for _ in range(n):
            self.edge_event.clear()
            await self.edge_event.wait()

    async def until(self, pred, edges=100000):
        for _ in range(edges):
            if pred():
                return
            await self.next_edge()
        raise AssertionError("condition not reached")

    # -- process ---------------------------------------------------------------
    async def count_cycles(self):
        from cocotb.triggers import RisingEdge as R
        while True:
            await R(self.d.clk)
            self.cycle += 1

    def _outputs(self):
        d = self.d
        valid = self.supply
        d.trng_out_valid.value = int(valid)
        d.trng_out_data.value = word(self.next) if valid else 0
        d.trng_gated.value = self.gated
        d.trng_startup_done.value = int(bool(self.startup_done and not self.startup_force_low))
        d.trng_alarm.value = self.alarm
        if self.alarm and self.alarm_set_cycle is None:
            self.alarm_set_cycle = self.cycle
        if not self.alarm:
            self.alarm_set_cycle = None

    async def run(self):
        d = self.d
        d.trng_clk.value = 0
        self._outputs()
        await Timer(self.phase_ns, unit="ns")
        half = self.period_ns // 2
        while self.running:
            # sample the core's drives just before the rising edge
            ready = bit(d.trng_out_ready)
            we = bit(d.trng_bus_we)
            if bit(d.trng_bus_re):
                self.violations.append(f"bus_re high at edge {self.edge + 1}")
            if not bit(d.rst_n):          # leftovers from a previous test while reset is applied
                ready = we = 0
            e = self.edge + 1
            if ready and self.supply:
                # the core drove out_ready from a t_fall that sampled the two periods before this edge
                prev1 = self.bad_hist[e - 1] if e >= 1 else 1
                prev2 = self.bad_hist[e - 2] if e >= 2 else 1
                if prev1 or prev2:
                    self.violations.append(f"word popped at edge {e} with bad history ({prev2},{prev1})")
                self.pops.append((e, self.next, word(self.next)))
                self.next += 1
            if we:
                addr = bit(d.trng_bus_addr)
                data = bit(d.trng_bus_wdata)
                self.writes.append((e, self.cycle, addr, data))
                if addr == W1C_ALARM:
                    if data & 7:
                        self.alarm = 0
                        self.alarm_clear_cycle = self.cycle
                elif addr == CTRL:
                    if data & 4:
                        self.startup_count = 0
                        self.startup_done = 0
                    self.enabled = bool(data & 1)
            self.edge = e
            d.trng_clk.value = 1
            if self.enabled and not self.alarm:
                if self.startup_count < self.startup_periods:
                    self.startup_count += 1
                    if self.startup_count >= self.startup_periods:
                        self.startup_done = 1
            await Timer(1, unit="ns")
            self._outputs()
            self.bad_hist.append(self.gated | int(not (self.startup_done and not self.startup_force_low)))
            self.edge_event.set()
            await Timer(half - 1, unit="ns")
            d.trng_clk.value = 0
            await Timer(self.period_ns - half, unit="ns")

    def start(self):
        cocotb.start_soon(self.count_cycles())
        cocotb.start_soon(self.run())
