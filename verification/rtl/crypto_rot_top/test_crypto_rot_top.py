"""cocotb bench for rtl/crypto_rot_top.v: everything through the register bus.

The bus is the only access the host has, and the bench uses nothing else
(no hierarchical DUT pokes; the sibling pins are driven by the port-protocol
stub in verification/rtl/trng_if/trngmodel.py, as the drbg_top bench does).
One cocotb module with shared bus helpers; the negative controls
(TOP_NEG_ZEROIZE, TOP_NEG_FAULT, KL_NEG_ZEROIZE) must make it fail.

    test_status_regs   reset state of STATUS/ZCAUSE/IRQ_*, W1C and RW
                       behaviour, and the class 1/2/4 fault responses
                       (undefined address, write to STATUS, read of a
                       write-only register, high address bits).
    test_kats          end-to-end published-vector KATs through the bus:
                       FIPS 197 vectors with the vector key loaded into a
                       slot (encrypt and decrypt), RFC 4231 cases 1-3 via
                       KEY_LOAD (case 4's 131-byte key is not bus-reachable
                       in v1, by 0009), derived-slot AES/HMAC cross-checked
                       against verification/model/*, KDF refusals surfacing,
                       DENY paths, and the class 3 busy-write gates
                       (AES_CTRL / DRBG_CTRL / KDF_CTRL while busy).
    test_drbg          instantiate/generate/reseed from the stub's words
                       against verification/model/ctr_drbg.py, the GEN_BITS
                       >128 refusal (ERR=3 without starting), generate before
                       instantiate, DRBG_OUT reads do not consume, and
                       software ZEROIZE -> re-instantiate.
    test_zeroize       the target-spec.md section 5 zeroize events: software
                       ZEROIZE, TRNG alarm (in to ALARM_ZEROIZED and out the
                       other side), TRNG gated (RESEED_REQUIRED, keys kept),
                       and zeroize during an in-flight AES operation.
    test_escalation    the section 5 bus-violation escalation: a second
                       violation within one operation zeroizes all slots
                       (FAULT_ZEROIZED, ZCAUSE bit 2), any violation during
                       key load escalates immediately, a busy-gated KDF_CTRL
                       write is a violation, and software ZEROIZE recovers.
    test_key_readback  with root key, four slot keys (derived and loaded), a
                       seeded DRBG and live engine outputs, a sweep of all
                       128 word addresses returns no 32-bit word of any key,
                       the root key, the seed or the DRBG state; err reads
                       return zero.

A correct KAT is a correctness claim only; this bench makes no key-isolation,
side-channel, timing or certification claim (the formal proofs are #46's
second child).
"""

import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "verification/rtl/trng_if"))

from trngmodel import TrngStub, bit  # noqa: E402
from verification.model import aes as model_aes  # noqa: E402
from verification.model import vectorlib  # noqa: E402
from verification.model.ctr_drbg import CtrDrbg  # noqa: E402
from verification.model.hmac_sha256 import hmac_sha256 as model_hmac  # noqa: E402
from verification.model.kdf import kdf_ctr_hmac_sha256  # noqa: E402

STATUS, CTRL, IRQ_MASK, IRQ_PEND, FAULT_CLS, ZCAUSE = range(0x00, 0x06)
AES_CTRL, AES_STATUS, AES_DIN, AES_DOUT = 0x10, 0x11, 0x12, 0x16
HMAC_CTRL, HMAC_STATUS, HMAC_MSG_CTL, HMAC_MSG_DATA, HMAC_MAC = 0x20, 0x21, 0x22, 0x23, 0x28
KDF_CTRL, KDF_STATUS, KDF_CTX, KEY_LOAD = 0x40, 0x41, 0x44, 0x4C
DRBG_CTRL, DRBG_STATUS, DRBG_OUT = 0x60, 0x61, 0x62

ST_RESET, ST_UNSEEDED, ST_READY, ST_RESEED_REQ, ST_ALARM_Z, ST_FAULT_Z = range(6)

WORDS = {
    STATUS, IRQ_MASK, IRQ_PEND, FAULT_CLS, ZCAUSE, AES_STATUS, HMAC_STATUS,
    KDF_STATUS, DRBG_STATUS,
} | set(range(AES_DOUT, AES_DOUT + 4)) | set(range(HMAC_MAC, HMAC_MAC + 8)) \
  | set(range(DRBG_OUT, DRBG_OUT + 4))
WRITE_ONLY = {CTRL, AES_CTRL, AES_DIN, AES_DIN + 1, AES_DIN + 2, AES_DIN + 3,
              HMAC_CTRL, HMAC_MSG_CTL, HMAC_MSG_DATA, KDF_CTRL,
              KEY_LOAD, DRBG_CTRL} | set(range(KDF_CTX, KDF_CTX + 8))
UNDEFINED = {a for a in range(0x80) if a not in WORDS and a not in WRITE_ONLY}

FIPS_PT = bytes.fromhex("3243f6a8885a308d313198a2e0370734")   # FIPS 197 App. B


def words(b):
    """Bytes -> list of big-endian 32-bit words (0009: word 0 is the MSW)."""
    return [int.from_bytes(b[4 * i:4 * i + 4], "big") for i in range(len(b) // 4)]


def from_words(ws):
    return b"".join(w.to_bytes(4, "big") for w in ws)


class Bus:
    """Single-cycle Wishbone master; one transfer takes two clk cycles."""

    def __init__(self, dut):
        self.d = dut
        self.proto_viol = []

    async def xfer(self, we, addr, wdata=0):
        d = self.d
        await FallingEdge(d.clk)
        d.cyc_i.value = 1
        d.stb_i.value = 1
        d.we_i.value = int(we)
        d.adr_i.value = addr
        d.dat_i.value = wdata
        await RisingEdge(d.clk)
        ack, err, rdata = bit(d.ack_o), bit(d.err_o), bit(d.dat_o)
        if ack + err != 1:
            self.proto_viol.append(f"xfer 0x{addr:02X}: ack={ack} err={err}")
        if err and rdata != 0:
            self.proto_viol.append(f"err response 0x{addr:02X} with dat={rdata:#x}")
        await FallingEdge(d.clk)
        d.cyc_i.value = 0
        d.stb_i.value = 0
        d.we_i.value = 0
        return rdata, err

    async def write(self, addr, data):
        _, err = await self.xfer(1, addr, data)
        return err

    async def read(self, addr):
        return await self.xfer(0, addr)


class Top:
    """Shared helpers: reset, stub, status polling, engine operations."""

    def __init__(self, dut):
        self.d = dut
        self.bus = Bus(dut)
        self.fails = []
        self.rng = random.Random(2026)
        self.root = bytes.fromhex(
            "603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4")
        self.stub = TrngStub(dut, ratio=40)
        self.drbg_model = CtrDrbg(use_df=True, key_bits=128, reseed_interval=65536)
        self.slot = {}                      # slot -> (kind, value bytes)

    def check(self, cond, msg):
        if not cond and len(self.fails) < 20:
            self.fails.append(msg)
        return cond

    async def cycles(self, n):
        for _ in range(n):
            await FallingEdge(self.d.clk)

    async def reset(self):
        d = self.d
        d.rst_n.value = 0
        d.cyc_i.value = 0
        d.stb_i.value = 0
        d.we_i.value = 0
        d.adr_i.value = 0
        d.dat_i.value = 0
        d.root_key.value = int.from_bytes(self.root, "big")
        d.root_key_valid.value = 0
        cocotb.start_soon(Clock(d.clk, 20, unit="ns").start())
        cocotb.start_soon(self.monitor())
        self.stub.start()
        await self.cycles(6)
        await FallingEdge(d.clk)
        d.rst_n.value = 1
        d.root_key_valid.value = 1
        for _ in range(20):
            await self.cycles(1)
            st, _ = await self.bus.read(STATUS)
            if st & 0x7 == ST_UNSEEDED:
                return
        self.check(False, "reset never reached UNSEEDED")

    async def monitor(self):
        """Independent bus-protocol checker (0005 shape)."""
        d = self.d
        while True:
            await RisingEdge(d.clk)
            stb, cyc = bit(d.stb_i), bit(d.cyc_i)
            ack, err = bit(d.ack_o), bit(d.err_o)
            if not (stb and cyc) and (ack or err):
                self.bus.proto_viol.append("response while cyc/stb low")
            if ack and err:
                self.bus.proto_viol.append("ack_o and err_o both high")

    def drain_proto(self):
        viol = self.bus.proto_viol
        self.bus.proto_viol = []
        return viol

    async def wait_ready(self):
        """Sibling start-up: STATUS mirrors must show ungated and started."""
        for _ in range(200_000):
            st, _ = await self.bus.read(STATUS)
            if (st >> 8) & 1 and not (st >> 6) & 1:
                return
            await self.cycles(1)
        self.check(False, "sibling never became ready")

    async def wait_state(self, want, limit=200_000):
        for _ in range(limit):
            st, _ = await self.bus.read(STATUS)
            if st & 0x7 == want:
                return st
            await self.cycles(1)
        self.check(False, f"STATE never reached {want}")
        return None

    async def poll(self, addr, bits, limit):
        for _ in range(limit):
            v, _ = await self.bus.read(addr)
            if v & bits:
                return v
            await self.cycles(1)
        self.check(False, f"poll 0x{addr:02X} bits {bits:#x} timed out")
        return None

    async def poll_clear(self, addr, bits, limit):
        for _ in range(limit):
            v, _ = await self.bus.read(addr)
            if not v & bits:
                return v
            await self.cycles(1)
        self.check(False, f"poll-clear 0x{addr:02X} bits {bits:#x} timed out")
        return None

    async def kdf_derive(self, slot, mask, ctx, parent=None):
        """Derive slot (parent = None for the root). Returns (err, status)."""
        for i, w in enumerate(words(ctx)):
            if await self.bus.write(KDF_CTX + i, w):
                return "ctx write faulted", None
        ctrl = (mask & 0xF) << 16
        if parent is None:
            ctrl |= 1 << 8
        else:
            ctrl |= (parent & 3) << 12
        ctrl |= (slot & 3) << 4 | 1
        if await self.bus.write(KDF_CTRL, ctrl):
            return "KDF_CTRL faulted", None
        st = await self.poll(KDF_STATUS, (1 << 1) | (1 << 2), 20_000)
        if st is None:
            return "KDF never finished", None
        if st & (1 << 2):
            return f"KDF err code {st >> 4 & 0xF}", st
        key = kdf_ctr_hmac_sha256(
            self.root, counter_bits=32, out_bits=256, before=b"",
            after=b"ROT-SLOT" + b"\x00"
            + bytes([0xFF if parent is None else parent, slot, mask]) + ctx
            + (256).to_bytes(4, "big"))
        self.slot[slot] = ("derive", key)
        return None, st

    async def kdf_load(self, slot, mask, key32):
        if await self.bus.write(KDF_CTRL, (mask & 0xF) << 16 | (slot & 3) << 4 | 1 << 2):
            return "LOAD_BEGIN faulted"
        for w in words(key32):
            if await self.bus.write(KEY_LOAD, w):
                return "KEY_LOAD faulted"
        st = await self.poll(KDF_STATUS, (1 << 1) | (1 << 2), 20_000)
        if st is None:
            return "load never finished"
        if st & (1 << 2):
            return f"load err code {st >> 4 & 0xF}"
        self.slot[slot] = ("load", key32)
        return None

    async def kdf_lock(self, slot):
        return await self.bus.write(KDF_CTRL, (slot & 3) << 4 | 2)

    async def aes_run(self, slot, decrypt, block16):
        for i, w in enumerate(words(block16)):
            if await self.bus.write(AES_DIN + i, w):
                return None, "DIN faulted"
        if await self.bus.write(AES_CTRL, (slot & 3) << 4 | decrypt << 1 | 1):
            return None, "start faulted"
        st = await self.poll(AES_STATUS, (1 << 1) | (1 << 2), 5_000)
        if st is None:
            return None, "AES never finished"
        if st & (1 << 2):
            return None, "denied"
        await self.poll_clear(AES_STATUS, 1, 100)
        deny, _ = await self.bus.read(AES_STATUS)
        if deny & (1 << 2):
            return None, "denied"
        out = b""
        for i in range(4):
            w, err = await self.bus.read(AES_DOUT + i)
            if err:
                return None, "DOUT read faulted"
            out += w.to_bytes(4, "big")
        return out, None

    async def feed_gap(self):
        """Let the serializer drain: the FEED gate refuses a word written while
        the previous one is still serializing (class 3 by 0009). MSG_READY
        stays high through the drain, so wait for five consecutive high probes."""
        ok = 0
        while ok < 5:
            await self.cycles(1)
            st, _ = await self.bus.read(HMAC_STATUS)
            ok = ok + 1 if st & (1 << 2) else 0

    async def hmac_run(self, slot, msg):
        if await self.bus.write(HMAC_CTRL, (slot & 3) << 4 | 1):
            return None, "start faulted"
        ready = await self.poll(HMAC_STATUS, 1 << 2, 20_000)
        if ready is None:
            return None, "MSG_READY never rose"
        n = len(msg)
        ctl_err = None
        if n == 0:
            if await self.bus.write(HMAC_MSG_CTL, (1 << 3) | (1 << 2)):
                ctl_err = f"MSG_CTL faulted (status {ready:#x})"
            if await self.bus.write(HMAC_MSG_DATA, 0):
                ctl_err = f"MSG_DATA faulted (status {ready:#x})"
        else:
            full, rem = divmod(n, 4)
            for i in range(full - (rem == 0)):
                if i:
                    await self.feed_gap()
                if await self.bus.write(HMAC_MSG_DATA, words(msg[4 * i:])[0]):
                    ctl_err = f"MSG_DATA faulted (status {ready:#x})"
            await self.feed_gap()
            if rem == 0:
                if await self.bus.write(HMAC_MSG_CTL, 3 | (1 << 2)):   # 4 bytes + LAST
                    ctl_err = f"MSG_CTL faulted (status {ready:#x})"
                if await self.bus.write(HMAC_MSG_DATA, words(msg[-4:])[0]):
                    ctl_err = f"MSG_DATA faulted (status {ready:#x})"
            else:
                if await self.bus.write(HMAC_MSG_CTL, (rem - 1) | (1 << 2)):
                    ctl_err = f"MSG_CTL faulted (status {ready:#x})"
                tail = msg[-rem:].ljust(4, b"\x00")
                if await self.bus.write(HMAC_MSG_DATA, words(tail)[0]):
                    ctl_err = f"MSG_DATA faulted (status {ready:#x})"
        if ctl_err:
            st, _ = await self.bus.read(HMAC_STATUS)
            return None, f"{ctl_err} now {st:#x}"
        st = await self.poll(HMAC_STATUS, 1 << 1, 60_000)
        if st is None:
            return None, "MAC_VALID never rose"
        tag = b""
        for i in range(8):
            w, err = await self.bus.read(HMAC_MAC + i)
            if err:
                return None, "MAC read faulted"
            tag += w.to_bytes(4, "big")
        return tag, None

    async def drbg_seed(self, reseed=False):
        """Instantiate (or reseed) from the stub's words; update the model."""
        before = len(self.stub.pops)
        if await self.bus.write(DRBG_CTRL, 2 if reseed else 1):
            return "DRBG_CTRL faulted"
        st = await self.poll(DRBG_STATUS, 1 << 1, 2_000_000)
        if st is None:
            return "DRBG never finished"
        err = (st >> 2) & 3
        if err:
            return f"DRBG err {err}"
        pops = [w for _, _, w in self.stub.pops[before:]]
        want = 8 if reseed else 16
        if len(pops) != want:
            return f"stub popped {len(pops)} words, want {want}"
        raw = from_words(pops)
        if reseed:
            self.drbg_model.reseed(raw)
        else:
            self.drbg_model.instantiate(raw[:32], raw[32:])
        return None

    async def drbg_generate(self, bits):
        if await self.bus.write(DRBG_CTRL, (bits & 0x7FF) << 16 | 3):
            return None, "generate faulted"
        st = await self.poll(DRBG_STATUS, 1 << 1, 200_000)
        if st is None:
            return None, "generate never finished"
        err = (st >> 2) & 3
        if err:
            return None, f"err {err}"
        out = b""
        for i in range(4):
            w, e = await self.bus.read(DRBG_OUT + i)
            if e:
                return None, "OUT read faulted"
            out += w.to_bytes(4, "big")
        return out, None

    async def sw_zeroize(self):
        if await self.bus.write(CTRL, 1):
            self.check(False, "ZEROIZE write faulted")
        for _ in range(200):
            await self.cycles(1)
            st, _ = await self.bus.read(STATUS)
            if st & 0x7 == ST_UNSEEDED and st >> 16 == 0:
                return
        self.check(False, "software ZEROIZE never settled")

    async def seed_and_derive(self):
        """Common setup: DRBG seeded, slot 0 AES-enc, slot 1 AES-dec,
        slot 2 HMAC, slot 3 loaded key. Returns True on success."""
        e = await self.drbg_seed()
        self.check(e is None, f"instantiate: {e}")
        if e:
            return False
        errs = []
        e, _ = await self.kdf_derive(0, 0b0001, self.rng.randbytes(32))
        if e:
            errs.append(f"slot0: {e}")
        e, _ = await self.kdf_derive(1, 0b0010, self.rng.randbytes(32))
        if e:
            errs.append(f"slot1: {e}")
        e, _ = await self.kdf_derive(2, 0b0100, self.rng.randbytes(32))
        if e:
            errs.append(f"slot2: {e}")
        load_key = self.rng.randbytes(32)
        e = await self.kdf_load(3, 0b0100, load_key)
        if e:
            errs.append(f"slot3: {e}")
        self.check(not errs, "seed_and_derive: " + "; ".join(errs))
        return not errs

    def secrets(self):
        """Every 32-bit word of key material the block currently holds."""
        forb = set(words(self.root))
        for _, val in self.slot.values():
            forb |= set(words(val))
        forb |= set(words(self.drbg_model.key))
        forb |= set(words(self.drbg_model.v))
        for _, _, w in self.stub.pops:
            forb.add(w)
        return forb


async def clear_faults(t):
    v, _ = await t.bus.read(FAULT_CLS)
    if v:
        await t.bus.write(FAULT_CLS, v)
    v, _ = await t.bus.read(IRQ_PEND)
    if v:
        await t.bus.write(IRQ_PEND, v)


@cocotb.test()
async def test_status_regs(dut):
    t = Top(dut)
    await t.reset()

    st, err = await t.bus.read(STATUS)
    t.check(not err and st & 0x7 == ST_UNSEEDED, f"post-reset STATE {st & 7:#x} err={err}")
    t.check(st >> 3 & 1 == 0 and st >> 16 == 0 and not (st >> 5) & 1,
            f"post-reset busy/slots/seeded: {st:#010x}")
    zc, _ = await t.bus.read(ZCAUSE)
    t.check(zc == 1, f"ZCAUSE after reset {zc:#x}, want bit 0")
    irq, _ = await t.bus.read(IRQ_PEND)
    t.check(irq == 0, f"IRQ_PEND after reset {irq:#x}")
    mask, _ = await t.bus.read(IRQ_MASK)
    t.check(mask == 0, f"IRQ_MASK after reset {mask:#x}")
    t.check(bit(dut.irq_o) == 0, "irq_o high after reset with mask clear")

    # W1C on ZCAUSE: write 1 clears, write 0 does not resurrect
    err = await t.bus.write(ZCAUSE, 1)
    t.check(not err, "ZCAUSE W1C write faulted")
    zc, _ = await t.bus.read(ZCAUSE)
    t.check(zc == 0, f"ZCAUSE not cleared: {zc:#x}")
    err = await t.bus.write(ZCAUSE, 0)
    zc, _ = await t.bus.read(ZCAUSE)
    t.check(zc == 0, f"ZCAUSE write-0 changed it: {zc:#x}")

    # IRQ_MASK is RW with one live bit
    await t.bus.write(IRQ_MASK, 0xFFFF_FFFF)
    mask, _ = await t.bus.read(IRQ_MASK)
    t.check(mask == 1, f"IRQ_MASK reserved bits not reserved: {mask:#x}")

    # fault classes 1, 2, 4 (class 3 gates are test_kats/test_escalation)
    cases = [
        (0x06, "read", "undefined 0x06", 1),
        (0x30, "read", "undefined 0x30", 1),
        (0x7F, "write", "undefined 0x7F", 1),
        (0x100, "read", "high address bit", 1),
        (STATUS, "write", "write to STATUS", 2),
        (CTRL, "read", "read of CTRL", 4),
        (AES_DIN, "read", "read of AES_DIN", 4),
        (KEY_LOAD, "read", "read of KEY_LOAD", 4),
    ]
    seen = 0
    for addr, kind, what, cls in cases:
        if kind == "read":
            data, err = await t.bus.read(addr)
            t.check(err == 1 and data == 0, f"{what}: err={err} dat={data:#x}")
        else:
            err = await t.bus.write(addr, 0)
            t.check(err == 1, f"{what}: write not refused (err={err})")
        fc, _ = await t.bus.read(FAULT_CLS)
        t.check(fc >> (cls - 1) & 1 == 1, f"{what}: FAULT_CLS class {cls} not recorded ({fc:#x})")
        seen |= 1 << (cls - 1)
        st, _ = await t.bus.read(STATUS)
        t.check(st >> 4 & 1 == 1, f"{what}: STATUS.FAULT not set")
        irq, _ = await t.bus.read(IRQ_PEND)
        t.check(irq & 2 == 2, f"{what}: ERROR pending not set")
        st, _ = await t.bus.read(STATUS)
        t.check(st & 0x7 == ST_UNSEEDED and st >> 16 == 0,
                f"{what}: single violation disturbed state ({st:#010x})")
        await t.bus.write(FAULT_CLS, 0xF)
        await t.bus.write(IRQ_PEND, 0x7)
        t.check(not t.drain_proto(), f"{what}: protocol violation on the bus")
    t.check(seen == 0b1011, f"classes exercised: {seen:#b}")  # class 3: test_kats/test_escalation

    # CTRL is write-only but a no-bit write is legal and stores nothing
    err = await t.bus.write(CTRL, 0)
    t.check(err == 0, "CTRL write with no bits refused")
    st, _ = await t.bus.read(STATUS)
    t.check(st & 0x7 == ST_UNSEEDED, "no-op CTRL write disturbed state")

    assert not t.fails, "first failing check: " + t.fails[0]


@cocotb.test()
async def test_kats(dut):
    t = Top(dut)
    await t.reset()
    await t.wait_ready()

    # ---- AES: FIPS 197 vectors with the vector key loaded into slot 3 ----
    vectors = vectorlib.parse_fips197(vectorlib.check_provenance("fips197.txt"))
    for section, v in vectors:
        key = v["KEY"]
        e = await t.kdf_load(3, 0b0001, key + bytes(16))
        t.check(e is None, f"{section}: AES-enc load: {e}")
        got, why = await t.aes_run(3, 0, v["PLAINTEXT"])
        t.check(got == v["CIPHERTEXT"], f"{section} encrypt: {why} got={got and got.hex()}")
        await t.sw_zeroize()                    # a mask change needs a fresh slot
        e = await t.kdf_load(3, 0b0010, key + bytes(16))
        t.check(e is None, f"{section}: AES-dec load: {e}")
        got, why = await t.aes_run(3, 1, v["CIPHERTEXT"])
        t.check(got == v["PLAINTEXT"], f"{section} decrypt: {why}")
        await t.sw_zeroize()
        await clear_faults(t)

    # ---- derived-slot AES: derivation + release + core, against the model ----
    e, _ = await t.kdf_derive(0, 0b0001, t.rng.randbytes(32))
    t.check(e is None, f"derived AES-enc slot: {e}")
    got, why = await t.aes_run(0, 0, FIPS_PT)
    t.check(got == model_aes.encrypt_block(t.slot[0][1][:16], FIPS_PT),
            f"derived-key encrypt: {why}")
    e, _ = await t.kdf_derive(1, 0b0010, t.rng.randbytes(32))
    t.check(e is None, f"derived AES-dec slot: {e}")
    ct = model_aes.encrypt_block(t.slot[0][1][:16], FIPS_PT)
    ct1 = model_aes.encrypt_block(t.slot[1][1][:16], FIPS_PT)
    got, why = await t.aes_run(1, 1, ct1)
    t.check(got == FIPS_PT, f"derived-key decrypt: {why} got={got and got.hex()} want={FIPS_PT.hex()}")

    # ---- HMAC: RFC 4231 cases 1-3 (case 4's 131-byte key is not on the bus;
    # case 5 is truncated output, also not applicable here) ----
    cases = vectorlib.parse_rfc4231(vectorlib.check_provenance("rfc4231.txt"))
    for case in (1, 2, 3):
        key, data, want = cases[case]
        e = await t.kdf_load(3, 0b0100, key.ljust(32, b"\x00"))
        t.check(e is None, f"RFC 4231 case {case} load: {e}")
        got, why = await t.hmac_run(3, data)
        t.check(got == want, f"RFC 4231 case {case}: {why} got={got and got.hex()}")
        got, why = await t.hmac_run(3, data)  # back-to-back op on the same slot
        t.check(got == want, f"RFC 4231 case {case} rerun: {why}")
        await clear_faults(t)
    # model cross-checks: empty message, partial final word, multi-word
    slot2_key = t.rng.randbytes(32)
    e = await t.kdf_load(2, 0b0100, slot2_key)
    t.check(e is None, f"model hmac load: {e}")
    for msg in (b"", b"abc", b"a" * 6, bytes(range(24))):
        got, why = await t.hmac_run(2, msg)
        t.check(got == model_hmac(slot2_key, msg), f"hmac {msg[:4]!r}..: {why}")

    # ---- KDF refusals surface on the bus ----
    t.check(await t.kdf_lock(0) == 0, "lock write faulted")
    e, st = await t.kdf_derive(0, 0b0001, t.rng.randbytes(32))
    t.check(e is not None and "err code 1" in e, f"derive into locked slot: {e}")
    e, _ = await t.kdf_derive(3, 0b0001, t.rng.randbytes(32))
    t.check(e is not None, f"derive over loaded slot: {e}")
    irq, _ = await t.bus.read(IRQ_PEND)
    t.check(irq & 2 == 2, "KDF refusal did not set ERROR pending")
    await clear_faults(t)

    # ---- DENY paths: no block runs, status says so ----
    got, why = await t.aes_run(2, 0, bytes(16))     # slot 2 is HMAC-only
    t.check(got is None and why == "denied", f"AES on HMAC slot ran: {got}")
    st, _ = await t.bus.read(AES_STATUS)
    t.check(st >> 2 & 1 == 1 and st & 1 == 0, f"AES_STATUS deny/busy {st:#x}")
    await clear_faults(t)

    # ---- class 3 gates: AES_CTRL / KDF_CTRL / DRBG_CTRL while busy ----
    await t.sw_zeroize()                    # the lock test left slot 0 locked
    await clear_faults(t)
    e, _ = await t.kdf_derive(0, 0b0001, t.rng.randbytes(32))
    t.check(e is None, f"gate setup slot0: {e}")
    for i, w in enumerate(words(FIPS_PT)):
        await t.bus.write(AES_DIN + i, w)
    await t.bus.write(AES_CTRL, 1)          # accepted start, block now runs
    err = await t.bus.write(AES_CTRL, 1)    # while busy: class 3
    t.check(err == 1, "AES_CTRL write while busy not refused")
    fc, _ = await t.bus.read(FAULT_CLS)
    t.check(fc & (1 << 2) == 1 << 2, f"busy AES_CTRL write: FAULT_CLS bit 2 not set ({fc:#x})")
    await t.poll(AES_STATUS, 1 << 1, 100)
    got = b""
    for i in range(4):
        w, _ = await t.bus.read(AES_DOUT + i)
        got += w.to_bytes(4, "big")
    t.check(got == model_aes.encrypt_block(t.slot[0][1][:16], FIPS_PT),
            f"original block disturbed by the refused write: {got.hex()}")
    await clear_faults(t)

    # the write must be refused while the DRBG is mid-instantiate, which then
    # completes untouched
    if await t.bus.write(DRBG_CTRL, 1):
        t.check(False, "instantiate write faulted")
    err = await t.bus.write(DRBG_CTRL, 1)   # while the DRBG is busy: class 3
    t.check(err == 1, "DRBG_CTRL write while busy not refused")
    await t.poll(DRBG_STATUS, 1 << 1, 2_000_000)
    st, _ = await t.bus.read(DRBG_STATUS)
    t.check((st >> 2) & 3 == 0, f"instantiate disturbed by the refused write: {st:#x}")
    await clear_faults(t)

    assert not t.fails, "first failing check: " + t.fails[0]


@cocotb.test()
async def test_drbg(dut):
    t = Top(dut)
    await t.reset()
    await t.wait_ready()

    st, _ = await t.bus.read(STATUS)
    t.check(st & 0x7 == ST_UNSEEDED and not (st >> 5) & 1, "not UNSEEDED at boot")

    # generate before instantiate: refused, error 1, no output
    out, why = await t.drbg_generate(128)
    t.check(why == "err 1" and out is None, f"generate before instantiate: {why}")
    blk, e = await t.bus.read(DRBG_OUT)
    t.check(e == 0 and blk == 0, f"DRBG_OUT not zero before any generate: {blk:#x}")
    await clear_faults(t)

    # GEN_BITS above 128: ERR=3 without starting the core (0009)
    err = await t.bus.write(DRBG_CTRL, (256 << 16) | 3)
    t.check(err == 0, "oversized generate refused on the bus")
    st = await t.poll(DRBG_STATUS, 1 << 1, 100)
    t.check(st is not None, "oversized generate: DONE not sticky")
    t.check((st >> 2) & 3 == 3, f"oversized generate: ERR {st}")
    st2, _ = await t.bus.read(DRBG_STATUS)
    t.check(st2 & 1 == 0, "oversized generate started the core")
    st3, _ = await t.bus.read(STATUS)
    t.check(st3 >> 15 & 1 == 0, "DRBG_BUSY with a refused generate")
    await clear_faults(t)

    # instantiate from the stub's words; model agrees; output matches
    e = await t.drbg_seed()
    t.check(e is None, f"instantiate: {e}")
    st, _ = await t.bus.read(STATUS)
    t.check(st & 0x7 == ST_READY and st >> 5 & 1 == 1, f"post-instantiate STATUS {st:#010x}")
    out, why = await t.drbg_generate(128)
    t.check(why is None and out == t.drbg_model.generate(16), f"generate 128: {why}")
    again = b""
    for i in range(4):
        w, _ = await t.bus.read(DRBG_OUT + i)
        again += w.to_bytes(4, "big")
    t.check(again == out, "DRBG_OUT read does not consume")

    # reseed from 8 fresh words; model agrees
    e = await t.drbg_seed(reseed=True)
    t.check(e is None, f"reseed: {e}")
    out, why = await t.drbg_generate(128)
    t.check(why is None and out == t.drbg_model.generate(16), f"generate after reseed: {why}")

    # software ZEROIZE: state gone, UNSEEDED, then re-instantiate works
    await t.sw_zeroize()
    st, _ = await t.bus.read(STATUS)
    t.check(not (st >> 5) & 1 and st >> 16 == 0, f"post-zeroize seeded/slots {st:#010x}")
    t.stub.pops.clear()
    e = await t.drbg_seed()
    t.check(e is None, f"re-instantiate after zeroize: {e}")
    out, why = await t.drbg_generate(128)
    t.check(why is None and out == t.drbg_model.generate(16), f"generate after re-instantiate: {why}")

    assert not t.fails, "first failing check: " + t.fails[0]


@cocotb.test()
async def test_zeroize(dut):
    t = Top(dut)
    await t.reset()
    await t.wait_ready()
    ok = await t.seed_and_derive()
    if not ok:
        assert not t.fails, "first failing check: " + t.fails[0]
        return
    st, _ = await t.bus.read(STATUS)
    t.check(st >> 16 == 0b1111 and st & 0x7 == ST_READY, f"setup STATUS {st:#010x}")

    # -- software ZEROIZE --
    await t.bus.write(ZCAUSE, 0xF)
    await t.sw_zeroize()
    st, _ = await t.bus.read(STATUS)
    t.check(st >> 16 == 0 and st >> 20 == 0 and not (st >> 5) & 1,
            f"sw ZEROIZE left state: {st:#010x}")
    t.check(st & 0x7 == ST_UNSEEDED, f"sw ZEROIZE STATE {st & 7}")
    zc, _ = await t.bus.read(ZCAUSE)
    t.check(zc & (1 << 3) == 1 << 3, f"ZCAUSE bit 3 not set ({zc:#x})")

    # -- zeroize during an in-flight operation --
    await clear_faults(t)
    ok = await t.seed_and_derive()
    if not ok:
        assert not t.fails, "first failing check: " + t.fails[0]
        return
    for i, w in enumerate(words(FIPS_PT)):
        await t.bus.write(AES_DIN + i, w)
    await t.bus.write(AES_CTRL, 1)          # slot 0, encrypt starts
    st, _ = await t.bus.read(AES_STATUS)
    t.check(st & 1 == 1, "AES not busy right after start")
    await t.bus.write(CTRL, 1)              # ZEROIZE mid-block
    st = await t.poll_clear(AES_STATUS, 1, 50)
    t.check(st is not None, "AES still busy after ZEROIZE")
    st, _ = await t.bus.read(STATUS)
    t.check(st >> 16 == 0 and not (st >> 5) & 1, f"mid-op zeroize left state {st:#010x}")
    out, _ = await t.bus.read(AES_DOUT)
    t.check(out == 0, f"partial AES result visible after zeroize: {out:#x}")
    zc, _ = await t.bus.read(ZCAUSE)
    t.check(zc & (1 << 3) == 1 << 3, f"mid-op zeroize ZCAUSE {zc:#x}")

    # -- TRNG alarm: ALARM_ZEROIZED, then recovery at the source --
    await clear_faults(t)
    ok = await t.seed_and_derive()
    if not ok:
        assert not t.fails, "first failing check: " + t.fails[0]
        return
    await t.bus.write(IRQ_MASK, 1)
    t.stub.raise_alarm()
    st = await t.wait_state(ST_ALARM_Z)
    if st is not None:
        t.check(st >> 16 == 0 and st >> 20 == 0 and not (st >> 5) & 1,
                f"alarm left key state: {st:#010x}")
        zc, _ = await t.bus.read(ZCAUSE)
        t.check(zc & 2 == 2, f"ZCAUSE alarm bit not set ({zc:#x})")
        irq, _ = await t.bus.read(IRQ_PEND)
        t.check(irq & 4 == 4, f"ALARM pending not set ({irq:#x})")
        t.check(bit(dut.irq_o) == 1, "irq_o low with ALARM pending and mask on")
    # recovery: the sibling's sequencer clears the alarm; back to UNSEEDED
    st = await t.wait_state(ST_UNSEEDED, 500_000)
    if st is not None:
        t.check(not (st >> 7) & 1, f"TRNG_ALARM mirror still set after recovery ({st:#010x})")
    await t.bus.write(ZCAUSE, 0xF)
    await t.bus.write(IRQ_PEND, 0x7)
    await t.sw_zeroize()                    # settle before re-seeding
    await clear_faults(t)
    t.stub.pops.clear()
    e = await t.drbg_seed()
    t.check(e is None, f"instantiate after alarm recovery: {e}")

    # -- TRNG gated while seeded: RESEED_REQUIRED, keys and DRBG kept --
    e, _ = await t.kdf_derive(0, 0b0001, t.rng.randbytes(32))
    t.check(e is None, f"gated-test derive: {e}")
    st, _ = await t.bus.read(STATUS)
    t.check(st & 0x7 == ST_READY, f"gated test needs READY, got {st & 7}")
    t.stub.gated_force = 1
    st = await t.wait_state(ST_RESEED_REQ)
    if st is not None:
        t.check(st >> 6 & 1 == 1, "TRNG_GATED mirror not set while gated")
        t.check(st >> 16 != 0, f"gated cleared the slots: {st:#010x}")
        t.check(st >> 5 & 1 == 1, "gated dropped SEEDED (keys and DRBG kept)")
    t.stub.gated_force = 0
    st = await t.wait_state(ST_READY)
    t.check(st is not None, "never returned to READY after ungated")

    assert not t.fails, "first failing check: " + t.fails[0]


@cocotb.test()
async def test_escalation(dut):
    t = Top(dut)
    await t.reset()
    await t.wait_ready()
    ok = await t.seed_and_derive()
    if not ok:
        assert not t.fails, "first failing check: " + t.fails[0]
        return

    # -- second violation within one (derivation) operation escalates --
    ctx = t.rng.randbytes(32)
    for i, w in enumerate(words(ctx)):
        await t.bus.write(KDF_CTX + i, w)
    err = await t.bus.write(KDF_CTRL, 0b0001 << 16 | 1 << 8 | 1)  # slot 0, root
    t.check(err == 0, "derive write faulted")
    _, err = await t.bus.read(CTRL)
    t.check(err == 1, "first in-operation violation not refused")
    fc, _ = await t.bus.read(FAULT_CLS)
    t.check(fc & (1 << 3) == 1 << 3, f"first violation: FAULT_CLS bit 4 not set ({fc:#x})")
    st, _ = await t.bus.read(STATUS)
    t.check(st >> 16 == 0b1111, f"first violation disturbed slots ({st:#010x})")
    _, err = await t.bus.read(CTRL)                   # second, same operation
    t.check(err == 1, "second violation not refused")
    st = await t.wait_state(ST_FAULT_Z)
    if st is not None:
        await t.cycles(8)                             # the zeroize pulse settles
        st, _ = await t.bus.read(STATUS)
        t.check(st >> 16 == 0, f"escalation left slots: {st:#010x}")
        t.check(not (st >> 5) & 1, f"escalation left SEEDED: {st:#010x}")
        zc, _ = await t.bus.read(ZCAUSE)
        t.check(zc & (1 << 2) == 1 << 2, f"ZCAUSE escalation bit not set ({zc:#x})")
    # recovery: software ZEROIZE from FAULT_ZEROIZED -> UNSEEDED
    await t.bus.write(CTRL, 1)
    st = await t.wait_state(ST_UNSEEDED)
    t.check(st is not None, "software ZEROIZE did not recover from FAULT_ZEROIZED")

    # -- any violation during key load escalates immediately --
    await clear_faults(t)
    ok = await t.seed_and_derive()
    if not ok:
        assert not t.fails, "first failing check: " + t.fails[0]
        return
    slot_key = t.rng.randbytes(4) + bytes(28)         # one word, then a violation
    err = await t.bus.write(KDF_CTRL, 0b0100 << 16 | 3 << 4 | 1 << 2)  # LOAD_BEGIN
    t.check(err == 0, "LOAD_BEGIN faulted")
    err = await t.bus.write(KEY_LOAD, words(slot_key)[0])
    t.check(err == 0, "first KEY_LOAD word faulted")
    _, err = await t.bus.read(CTRL)                   # violation inside the window
    t.check(err == 1, "key-load violation not refused")
    st = await t.wait_state(ST_FAULT_Z)
    if st is not None:
        await t.cycles(8)                             # the zeroize pulse settles
        st, _ = await t.bus.read(STATUS)
        t.check(st >> 16 == 0, f"key-load escalation left slots: {st:#010x}")
        zc, _ = await t.bus.read(ZCAUSE)
        t.check(zc & (1 << 2) == 1 << 2, f"key-load ZCAUSE {zc:#x}")
    await t.bus.write(CTRL, 1)
    await t.wait_state(ST_UNSEEDED)

    # -- a busy-gated KDF_CTRL write is a violation; second one escalates --
    await clear_faults(t)
    ok = await t.seed_and_derive()
    if not ok:
        assert not t.fails, "first failing check: " + t.fails[0]
        return
    err = await t.bus.write(KDF_CTRL, 0b0001 << 16 | 1 << 8 | 1)  # derive, accepted
    t.check(err == 0, "derive write faulted")
    err = await t.bus.write(KDF_CTRL, 0b0001 << 16 | 1 << 8 | 1)  # busy: class 3
    t.check(err == 1, "KDF_CTRL write while busy not refused")
    st, _ = await t.bus.read(STATUS)
    t.check(st >> 16 == 0b1111 and st & 0x7 != ST_FAULT_Z,
            f"first busy-gate write escalated early ({st:#010x})")
    err = await t.bus.write(KDF_CTRL, 0b0001 << 16 | 1 << 8 | 1)  # still busy
    t.check(err == 1, "second busy-gate write not refused")
    st = await t.wait_state(ST_FAULT_Z)
    t.check(st is not None, "busy-gate pair did not escalate")

    assert not t.fails, "first failing check: " + t.fails[0]


@cocotb.test()
async def test_key_readback(dut):
    t = Top(dut)
    await t.reset()
    await t.wait_ready()
    ok = await t.seed_and_derive()
    if not ok:
        assert not t.fails, "first failing check: " + t.fails[0]
        return
    out, why = await t.drbg_generate(128)
    t.check(why is None, f"readback generate: {why}")

    forb = t.secrets()
    t.check(len(forb) > 20, "secret word set suspiciously small")

    leak = []
    for addr in range(0x80):
        data, err = await t.bus.read(addr)
        if addr in WRITE_ONLY or addr in UNDEFINED:
            t.check(err == 1 and data == 0,
                    f"addr 0x{addr:02X}: err={err} dat={data:#x} (want refused/zero)")
        else:
            t.check(err == 0, f"addr 0x{addr:02X}: readable register faulted")
            if err == 0 and data != 0 and data in forb:
                leak.append((addr, data))
    t.check(not leak, f"KEY MATERIAL READABLE: {leak}")

    assert not t.fails, "first failing check: " + t.fails[0]
