"""cocotb bench for rtl/keyladder/keyladder.v.

Scores the key ladder against verification/model/kdf.py (the layout of
decision record 0003: counter 00000001, label ROT-SLOT, 0x00, 35-byte context,
[L]=00000100) and checks the root-of-trust behaviours the issue lists:

  derivation   root -> slot and root -> slot -> slot for every use_mask bit
               individually and all four together, several (index, context)
               cases; masks without HMAC/AES bits are checked through a child
               derivation (the slot value has no direct engine path).
  permission   every (slot, engine, mask bit): release iff the bit is set,
               and the key output is zero otherwise.
  lock         every refusal leaves all slot state bit-identical (the bench
               peeks at the slot flops s0..s3, v, m, l, d; simulation only).
  load         write-only software load, same lock/mask rules.
  zeroize      all slots zero, refusals re-armed, a derivation in flight
               leaves no partial key.

Only the AES key port's upper half (slot[255:128]) is observable for masks that
carry only AES bits; that half is compared. CAVP KDFCTR_gen.rsp vectors are not
used here: they carry arbitrary fixed input data, not the 0003 layout.
"""

import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from verification.model import kdf_ctr_hmac_sha256  # noqa: E402

E_LOCKED_DST, E_PARENT_INVALID, E_NO_KDF_PARENT, E_MASK_CHANGE = 1, 2, 3, 4
E_DEPTH, E_BUSY, E_ROOT_INVALID, E_SELF, E_LOCK_INVALID = 5, 6, 7, 8, 9
ROOT = None
MAX_DERIVE = 3000

fails = []


def check(cond, msg):
    if not cond and len(fails) < 20:
        fails.append(msg)
    return cond


def model_derive(ki, slot, parent_id, mask, ctx):
    context = bytes([parent_id, slot, mask]) + ctx
    assert len(context) == 35
    return kdf_ctr_hmac_sha256(
        ki, counter_bits=32, out_bits=256, before=b"",
        after=b"ROT-SLOT" + b"\x00" + context + (256).to_bytes(4, "big"))


class Bench:
    def __init__(self, dut):
        self.d = dut
        self.rng = random.Random(1)
        self.root = self.rng.randbytes(32)
        self.derived = 0

    async def reset(self):
        d = self.d
        d.rst_n.value = 0
        for s in ("zeroize", "root_key_valid", "cmd_derive", "cmd_lock", "ld_begin", "cmd_slot",
                  "cmd_parent_root", "cmd_parent", "cmd_mask", "cmd_ctx", "ld_valid", "ld_data",
                  "hmac_req", "hmac_slot", "aes_req", "aes_dec", "aes_slot"):
            getattr(d, s).value = 0
        d.root_key.value = int.from_bytes(self.root, "big")
        await ClockCycles(d.clk, 3)
        await FallingEdge(d.clk)
        d.rst_n.value = 1
        d.root_key_valid.value = 1
        await RisingEdge(d.clk)
        await FallingEdge(d.clk)

    async def zeroize(self):
        d = self.d
        await FallingEdge(d.clk)
        d.zeroize.value = 1
        await FallingEdge(d.clk)
        d.zeroize.value = 0

    def snap(self):
        d = self.d
        out = []
        for n in range(4):
            for r in ("s", "v", "m", "l", "d"):
                out.append(int(getattr(d, f"{r}{n}").value))
        return tuple(out)

    async def pulse(self, **sig):
        """One-cycle command; returns (err_code or 0) seen the cycle after."""
        d = self.d
        await FallingEdge(d.clk)
        for k, v in sig.items():
            getattr(d, k).value = v
        await RisingEdge(d.clk)
        await FallingEdge(d.clk)
        for k in sig:
            if k.startswith(("cmd_derive", "cmd_lock", "ld_begin")):
                getattr(d, k).value = 0
        err = int(d.err_code.value) if int(d.err_pulse.value) else 0
        return err

    async def wait_done(self, limit=MAX_DERIVE):
        d = self.d
        for _ in range(limit):
            if int(d.done_pulse.value):
                return True
            await RisingEdge(d.clk)
            await FallingEdge(d.clk)
        return False

    async def derive(self, slot, mask, ctx, parent=ROOT, wait=True):
        d = self.d
        d.cmd_ctx.value = int.from_bytes(ctx, "big")
        sig = dict(cmd_derive=1, cmd_slot=slot, cmd_mask=mask,
                   cmd_parent_root=int(parent is ROOT), cmd_parent=parent or 0)
        err = await self.pulse(**sig)
        if err or not wait:
            return err
        ok = await self.wait_done()
        check(ok, f"derive slot {slot} never completed")
        self.derived += 1
        return 0

    async def lock(self, slot):
        return await self.pulse(cmd_lock=1, cmd_slot=slot)

    async def load(self, slot, mask, key, words=8, begin_only=False):
        d = self.d
        err = await self.pulse(ld_begin=1, cmd_slot=slot, cmd_mask=mask)
        if err or begin_only:
            return err
        for i in range(words):
            await FallingEdge(d.clk)
            d.ld_valid.value = 1
            d.ld_data.value = int.from_bytes(key[4 * i:4 * i + 4], "big")
            await RisingEdge(d.clk)
        await FallingEdge(d.clk)
        d.ld_valid.value = 0
        await RisingEdge(d.clk)
        await FallingEdge(d.clk)
        return 0

    async def release(self, engine, slot):
        """engine: 'hmac' | 'enc' | 'dec'. Returns (key int, deny bit)."""
        d = self.d
        await FallingEdge(d.clk)
        if engine == "hmac":
            d.hmac_req.value = 1
            d.hmac_slot.value = slot
        else:
            d.aes_req.value = 1
            d.aes_dec.value = int(engine == "dec")
            d.aes_slot.value = slot
        await RisingEdge(d.clk)
        await FallingEdge(d.clk)
        key = int(d.hmac_key.value if engine == "hmac" else d.aes_key.value)
        deny = int(d.rel_deny.value)
        d.hmac_req.value = 0
        d.aes_req.value = 0
        return key, deny


def ctx_for(rng):
    return rng.randbytes(32)


@cocotb.test()
async def test_keyladder(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    b = Bench(dut)
    rng = b.rng
    await b.reset()
    ZERO = b"\x00" * 32
    ENG_BIT = {"enc": 0, "dec": 1, "hmac": 2}

    # ---- derivation: root -> slot, every mask bit individually and together ----
    for mask in (1, 2, 4, 8, 15):
        for slot in range(4):
            ctx = ZERO if (mask + slot) % 3 == 0 else ctx_for(rng)
            await b.zeroize()
            err = await b.derive(slot, mask, ctx)
            check(err == 0, f"derive refused mask {mask} slot {slot}: {err}")
            want = model_derive(b.root, slot, 0xFF, mask, ctx)
            if mask & 4:
                got, _ = await b.release("hmac", slot)
                check(got.to_bytes(32, "big") == want, f"root->slot{slot} mask {mask}: hmac_key mismatch")
            elif mask & 3:
                eng = "enc" if mask & 1 else "dec"
                got, _ = await b.release(eng, slot)
                check(got == int.from_bytes(want[:16], "big"), f"root->slot{slot} mask {mask}: aes_key mismatch")
            else:
                # KDF-parent only: check through a child derived from it
                cctx = ctx_for(rng)
                err = await b.derive((slot + 1) % 4, 4, cctx, parent=slot)
                check(err == 0, f"child of slot {slot} refused: {err}")
                got, _ = await b.release("hmac", (slot + 1) % 4)
                check(got.to_bytes(32, "big") == model_derive(want, (slot + 1) % 4, slot, 4, cctx),
                      f"slot{slot}->child mismatch")
    # different masks give different keys for the same slot and context
    ctx = ctx_for(rng)
    await b.zeroize()
    await b.derive(0, 0b0100, ctx)
    k1, _ = await b.release("hmac", 0)
    await b.zeroize()
    await b.derive(0, 0b1100, ctx)
    k2, _ = await b.release("hmac", 0)
    check(k1 != k2 and k1 != 0, "mask is not part of the context")

    # ---- chain root -> slot -> slot and depth ----
    for slot_a, slot_b in ((0, 1), (3, 2), (1, 3)):
        await b.zeroize()
        ca, cb = ctx_for(rng), ctx_for(rng)
        await b.derive(slot_a, 0b1100, ca)
        await b.derive(slot_b, 0b0100, cb, parent=slot_a)
        ka = model_derive(b.root, slot_a, 0xFF, 0b1100, ca)
        kb = model_derive(ka, slot_b, slot_a, 0b0100, cb)
        got, _ = await b.release("hmac", slot_b)
        check(got.to_bytes(32, "big") == kb, f"chain {slot_a}->{slot_b} mismatch")
    await b.zeroize()
    await b.derive(0, 0b1100, ZERO)
    await b.derive(1, 0b1100, ZERO, parent=0)
    snap = b.snap()
    check(await b.derive(2, 0b0100, ZERO, parent=1) == E_DEPTH, "depth 3 not refused")
    check(b.snap() == snap, "depth refusal changed state")
    # back-to-back derivations, rederive with same mask and new context
    await b.zeroize()
    for i in range(4):
        await b.derive(i, 0b0100, bytes([i]) * 32)
    for i in range(4):
        got, _ = await b.release("hmac", i)
        check(got.to_bytes(32, "big") == model_derive(b.root, i, 0xFF, 4, bytes([i]) * 32),
              f"back-to-back slot {i}")
    c2 = ctx_for(rng)
    check(await b.derive(2, 0b0100, c2) == 0, "rederive same mask refused")
    got, _ = await b.release("hmac", 2)
    check(got.to_bytes(32, "big") == model_derive(b.root, 2, 0xFF, 4, c2), "rederive value")

    # ---- permission bench ----
    for mask in range(16):
        await b.zeroize()
        for slot in range(4):
            await b.derive(slot, mask, bytes([slot, mask]) * 16)
        for slot in range(4):
            want = model_derive(b.root, slot, 0xFF, mask, bytes([slot, mask]) * 16)
            for eng, bit in ENG_BIT.items():
                got, deny = await b.release(eng, slot)
                allowed = bool(mask >> bit & 1)
                exp = int.from_bytes(want if eng == "hmac" else want[:16], "big") if allowed else 0
                check(got == exp, f"permission slot {slot} {eng} mask {mask:04b}: key {'wrong' if allowed else 'leaked'}")
                check(deny == (0 if allowed else 1), f"permission slot {slot} {eng} mask {mask:04b}: deny={deny}")

    # ---- lock and refusal bench ----
    await b.zeroize()
    await b.derive(0, 0b1100, ctx_for(rng))
    await b.derive(1, 0b1000, ctx_for(rng))             # KDF-parent only, depth 1
    await b.derive(2, 0b0100, ctx_for(rng))             # no KDF-parent
    await b.derive(3, 0b1100, ctx_for(rng), parent=0)   # depth 2
    check(await b.lock(1) == 0, "lock refused")
    snap = b.snap()
    cases = [
        ("derive into locked slot", lambda: b.derive(1, 0b1000, ZERO), E_LOCKED_DST),
        ("derive from locked parent", lambda: b.derive(2, 0b0100, ZERO, parent=1), E_PARENT_INVALID),
        ("parent without KDF-parent", lambda: b.derive(0, 0b1100, ZERO, parent=2), E_NO_KDF_PARENT),
        ("mask change after derivation", lambda: b.derive(2, 0b0101, ZERO), E_MASK_CHANGE),
        ("parent chain deeper than 2", lambda: b.derive(2, 0b0100, ZERO, parent=3), E_DEPTH),
        ("load into locked slot", lambda: b.load(1, 0b1000, ZERO, begin_only=True), E_LOCKED_DST),
        ("load mask change", lambda: b.load(2, 0b0001, ZERO, begin_only=True), E_MASK_CHANGE),
    ]
    for name, fn, want in cases:
        err = await fn()
        check(err == want, f"{name}: err {err}, expected {want}")
        check(b.snap() == snap, f"{name}: state changed")
    await b.zeroize()
    await b.derive(0, 0b1100, ZERO)
    await b.derive(1, 0b1100, ZERO, parent=0)
    snap = b.snap()
    for name, fn, want in (
        ("derive from never-derived parent", lambda: b.derive(2, 0b0100, ZERO, parent=3), E_PARENT_INVALID),
        ("derive slot from itself", lambda: b.derive(0, 0b1100, ZERO, parent=0), E_SELF),
        ("lock of never-derived slot", lambda: b.lock(3), E_LOCK_INVALID),
    ):
        err = await fn()
        check(err == want, f"{name}: err {err}, expected {want}")
        check(b.snap() == snap, f"{name}: state changed")
    dut.root_key_valid.value = 0
    err = await b.derive(2, 0b0100, ZERO)
    check(err == E_ROOT_INVALID, f"root invalid: {err}")
    check(b.snap() == snap, "root invalid changed state")
    dut.root_key_valid.value = 1
    # busy: a second command while a derivation runs
    await b.derive(2, 0b0100, ZERO, wait=False)
    for _ in range(5):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    check(int(dut.busy.value) == 1, "busy low during derivation")
    err = await b.derive(3, 0b0100, ZERO)
    check(err == E_BUSY, f"busy refusal: {err}")
    check(await b.wait_done(), "in-flight derivation did not finish")
    check(int(dut.v3.value) == 0, "refused derive-while-busy wrote slot 3")
    # a locked slot cannot be rewritten or have its mask changed until zeroize
    await b.lock(0)
    await b.derive(0, 0b1100, ctx_for(rng))
    await b.derive(0, 0b0001, ctx_for(rng))
    check(await b.derive(0, 0b1100, ZERO) == E_LOCKED_DST, "locked slot rewritten")
    await b.zeroize()
    check(await b.derive(0, 0b0001, ZERO) == 0, "refusal not re-armed after zeroize")

    # ---- software load ----
    await b.zeroize()
    key = rng.randbytes(32)
    check(await b.load(1, 0b1100, key, words=3) == 0, "load refused")
    got, _ = await b.release("hmac", 1)
    check(got == 0, "partial load visible")
    await b.zeroize()
    check(await b.load(1, 0b1100, key) == 0, "load refused")
    await ClockCycles(dut.clk, 2)
    got, _ = await b.release("hmac", 1)
    check(got.to_bytes(32, "big") == key, "loaded key mismatch")
    check(await b.derive(2, 0b0100, ZERO, parent=1) == 0, "derive from loaded parent refused")
    got, _ = await b.release("hmac", 2)
    check(got.to_bytes(32, "big") == model_derive(key, 2, 1, 4, ZERO), "child of loaded key")
    check(await b.load(1, 0b0100, key, begin_only=True) == E_MASK_CHANGE, "load mask change allowed")
    await b.lock(1)
    check(await b.load(1, 0b1100, key, begin_only=True) == E_LOCKED_DST, "load into locked slot")

    # ---- zeroize bench ----
    await b.zeroize()
    for s in range(4):
        await b.derive(s, 0b1111, bytes([s]) * 32)
    await b.lock(2)
    await b.zeroize()
    snap = b.snap()
    check(all(x == 0 for x in snap), "zeroize left slot state nonzero")
    for s in range(4):
        for eng in ENG_BIT:
            got, deny = await b.release(eng, s)
            check(got == 0, f"slot {s} {eng} nonzero after zeroize")
    check(await b.derive(2, 0b1111, ZERO) == 0, "locked slot not re-armed")
    # zeroize mid-derivation at several points: no partial key survives
    for cut in (3, 40, 160, 400):
        await b.zeroize()
        await b.derive(1, 0b1100, ZERO, wait=False)
        await ClockCycles(dut.clk, cut)
        await b.zeroize()
        await ClockCycles(dut.clk, 700)
        check(all(x == 0 for x in b.snap()), f"zeroize at {cut} left state")
        check(int(dut.busy.value) == 0, f"busy after zeroize at {cut}")
        check(await b.derive(1, 0b1100, ZERO) == 0, f"derive after abort at {cut}")
        got, _ = await b.release("hmac", 1)
        check(got.to_bytes(32, "big") == model_derive(b.root, 1, 0xFF, 0b1100, ZERO),
              f"derive after abort at {cut}: value")

    dut._log.info(f"SUMMARY derivations={b.derived} failures={len(fails)}")
    for f in fails:
        dut._log.error(f"first failing check: {f}")
    assert not fails, "first failing check: " + fails[0]
