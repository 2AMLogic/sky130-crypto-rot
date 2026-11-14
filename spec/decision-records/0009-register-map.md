# 0009 - Register map: offsets, access types, STATUS layout, key-load window

Status: Accepted. Date: 2026-10-29.

## Decision

The register interface of `crypto_rot_top` is the flat, word-addressed map
below, on the bus ratified in 0005. `adr_i` is a 7-bit word address (128
words); any address bit above bit 6 set is an undefined address. The map is
grouped by engine and derived from the ports of `rtl/aes/aes_core.v`,
`rtl/hmac/hmac_sha256.v`, `rtl/keyladder/keyladder.v`, `rtl/drbg/drbg_top.v`
and `rtl/trng_if/trng_if.v`. It adds no capability those blocks lack; the
top level is wiring, a bus front end, and the small amount of control state
named in the Notes below. Nothing in `target-spec.md` section 5 or 0005 is
changed: the lifecycle states, the zeroize event list and the four bus
violation classes stay as ratified.

Access types: **RO** read-only; **WO** write-only (a read is violation class
4: it returns zero with `err_o`, never data); **RW** read/write; **W1C**
readable, and a write of 1 to a bit clears it (a write of 0 does nothing).
A write to an RO location is violation class 2. Reserved bits read as zero
and ignore writes. Data words are big-endian: word 0 of a multi-word value
holds its most significant 32 bits, and byte 0 of a message word is
`[31:24]`, matching the byte order of the blocks.

The machine-checked table (`verification/check_regmap.py` parses exactly
these rows). `Gate` names the engine whose busy state refuses a write
(violation class 3); `-` means the write is never refused for busy. `Ports`
names the existing block ports the location is wired to.

| Offset | Name | Access | Gate | Ports |
|---|---|---|---|---|
| 0x00 | STATUS | RO | - | `slot_valid`, `slot_locked`, `seeded`, `trng_gated`, `trng_startup_done`, `root_key_valid`, engine `busy` |
| 0x01 | CTRL | WO | - | `zeroize`, `sw_zeroize` |
| 0x02 | IRQ_MASK | RW | - | `irq_o` |
| 0x03 | IRQ_PEND | W1C | - | `irq_o` |
| 0x04 | FAULT_CLS | W1C | - | `err_o` |
| 0x05 | ZCAUSE | W1C | - | `zeroize`, `alarm_zeroized` |
| 0x10 | AES_CTRL | WO | AES | `start`, `decrypt`, `aes_req`, `aes_dec`, `aes_slot` |
| 0x11 | AES_STATUS | RO | - | `busy`, `done`, `rel_deny` |
| 0x12-0x15 | AES_DIN[0..3] | WO | AES | `block_in` |
| 0x16-0x19 | AES_DOUT[0..3] | RO | - | `block_out` |
| 0x20 | HMAC_CTRL | WO | HMAC | `start`, `clear`, `hmac_req`, `hmac_slot` |
| 0x21 | HMAC_STATUS | RO | - | `busy`, `mac_valid`, `in_ready`, `rel_deny` |
| 0x22 | HMAC_MSG_CTL | WO | HMAC-FEED | `in_last`, `in_empty` |
| 0x23 | HMAC_MSG_DATA | WO | HMAC-FEED | `in_valid`, `in_data` |
| 0x28-0x2F | HMAC_MAC[0..7] | RO | - | `mac` |
| 0x40 | KDF_CTRL | WO | KDF | `cmd_derive`, `cmd_lock`, `ld_begin`, `cmd_slot`, `cmd_parent_root`, `cmd_parent`, `cmd_mask` |
| 0x41 | KDF_STATUS | RO | - | `busy`, `done_pulse`, `err_pulse`, `err_code` |
| 0x44-0x4B | KDF_CTX[0..7] | WO | KDF | `cmd_ctx` |
| 0x4C | KEY_LOAD | WO | KDF-LOAD | `ld_valid`, `ld_data` |
| 0x60 | DRBG_CTRL | WO | DRBG | `req_inst`, `req_reseed`, `req_gen`, `gen_bits` |
| 0x61 | DRBG_STATUS | RO | - | `busy`, `done`, `err`, `seeded`, `reseed_required`, `alarm_zeroized`, `blk_valid` |
| 0x62-0x65 | DRBG_OUT[0..3] | RO | - | `blk_data` |

Every word address not in the table (0x06-0x0F, 0x1A-0x1F, 0x24-0x27,
0x30-0x3F, 0x42-0x43, 0x4D-0x5F, 0x66-0x7F) is undefined: any access
returns zero with `err_o` (class 1). The script prints the unmapped ranges
from the table so this list is checked.

### Gate meanings (class 3, write while the addressed engine is busy)

- `AES`: the `aes_core` `busy` output is high.
- `HMAC`: the `hmac_sha256` `busy` output is high. `HMAC_CTRL` with only the
  `CLEAR` bit set is exempt (abort must work while busy).
- `HMAC-FEED`: a message word is still being serialized into `in_data`, or
  `HMAC_STATUS.MSG_READY` (`in_ready`) is low for any other reason, including
  no operation having been started. This reuses class 3; no fifth class is
  added.
- `KDF`: `keyladder` `busy` is high (this includes the key-load sequence).
- `KDF-LOAD`: `KEY_LOAD` is accepted only while the ladder is in its key-load
  sequence after a `LOAD_BEGIN` command; a write at any other time is class 3.
- `DRBG`: `drbg_top` `busy` is high.

### Register layouts

`STATUS` (0x00, RO):

| Bits | Field | Meaning |
|---|---|---|
| [2:0] | STATE | 0 RESET, 1 UNSEEDED, 2 READY, 3 RESEED_REQUIRED, 4 ALARM_ZEROIZED, 5 FAULT_ZEROIZED (the section 5 states) |
| [3] | BUSY | any engine busy |
| [4] | FAULT | `FAULT_CLS` is nonzero |
| [5] | SEEDED | DRBG `seeded` |
| [6] | TRNG_GATED | synchronized mirror of the sibling's `gated` |
| [7] | TRNG_ALARM | synchronized mirror of the sibling's `alarm` |
| [8] | TRNG_STARTUP_DONE | mirror of `startup_done` |
| [9] | ROOT_KEY_VALID | mirror of the `root_key_valid` pin (a flag, not the key) |
| [12] | AES_BUSY | `aes_core` `busy` |
| [13] | HMAC_BUSY | `hmac_sha256` `busy` |
| [14] | KDF_BUSY | `keyladder` `busy` |
| [15] | DRBG_BUSY | `drbg_top` `busy` |
| [19:16] | SLOT_VALID | `slot_valid[3:0]`, slot 0 in bit 16 |
| [23:20] | SLOT_LOCKED | `slot_locked[3:0]`, slot 0 in bit 20 |
| others | reserved | read zero |

`CTRL` (0x01, WO): bit 0 `ZEROIZE`, the software `ZEROIZE` command of
section 5 (acts as a one-cycle command; it is never stored, so a read
returns zero with `err_o`). Other bits are reserved and ignored.

`IRQ_MASK` (0x02, RW): bit 0 `EN`. `irq_o = EN & (DONE | ERROR | ALARM)`
where those are the `IRQ_PEND` bits, as stated in section 6 (single mask; a
per-source mask is the section 6 stretch).

`IRQ_PEND` (0x03, W1C), sticky: bit 0 `DONE` (set when any engine
completes: AES `done`, HMAC `mac_valid`, KDF `done_pulse`, DRBG `done`);
bit 1 `ERROR` (set on any bus violation, a KDF `err_pulse`, a nonzero DRBG
`err`, or a `rel_deny`); bit 2 `ALARM` (set when the synchronized TRNG alarm
zeroizes). Clearing `ALARM` clears the pending bit only; it does not recover
the state, which `STATUS.STATE` still shows.

`FAULT_CLS` (0x04, W1C), sticky, one bit per section 5 violation class:
bit 0 undefined address, bit 1 write to a read-only register, bit 2 write
while the addressed engine is busy, bit 3 read of a write-only location.
`STATUS.FAULT` is the OR of its bits. This is the register-level observation
point of the `FAULT` status in section 5.

`ZCAUSE` (0x05, W1C), sticky, the observation point of each section 5
zeroize event: bit 0 reset (set by reset, so the first read after power-up
shows it), bit 1 TRNG `alarm`, bit 2 bus-violation escalation (second
violation, or any violation during key load), bit 3 software `ZEROIZE`.
Observable effects of any zeroize are also `SLOT_VALID` = 0, `SLOT_LOCKED` =
0 and `SEEDED` = 0 in `STATUS`. The TRNG `gated` event (seed buffer only, no
state loss) is observed as `STATUS.TRNG_GATED` and, if it persists,
`STATE` = RESEED_REQUIRED.

`AES_CTRL` (0x10, WO): bit 0 `START`, bit 1 `DECRYPT`, [5:4] `SLOT`
(`aes_slot`). A start whose slot is invalid or whose use-mask forbids the
direction is denied by the ladder (`rel_deny`); no block runs.
`AES_STATUS` (0x11, RO): bit 0 `BUSY`, bit 1 `DONE` (sticky until the next
`START`), bit 2 `DENY` (the last `START` was denied).
`AES_DIN` (0x12-0x15, WO) is `block_in`, `AES_DOUT` (0x16-0x19, RO) is
`block_out`, which the core already holds at zero until `done`.

`HMAC_CTRL` (0x20, WO): bit 0 `START`, bit 1 `CLEAR`, [5:4] `SLOT`
(`hmac_slot`). The key is always a slot key: `key_long` is tied to 0 and
`key_len` to 32 (a shorter key is the same HMAC when zero-extended to 32
bytes, since HMAC pads the key with zeros). Keys longer than 32 bytes are not
reachable from the bus in v1. `HMAC_STATUS` (0x21, RO): bit 0 `BUSY`, bit 1
`MAC_VALID`, bit 2 `MSG_READY`, bit 3 `DENY`. `HMAC_MSG_CTL` (0x22, WO):
[1:0] `NBYTES_M1` (bytes in the next word, minus one), bit 2 `LAST`, bit 3
`EMPTY` (with `LAST`: end the message with no data byte; `NBYTES_M1` is
ignored). Every encoding is valid. A write to `HMAC_MSG_DATA` (0x23, WO)
serializes the word's bytes, most significant first, into `in_data`.
`HMAC_MAC` (0x28-0x2F, RO) is `mac`, zero while `mac_valid` is low.

`KDF_CTRL` (0x40, WO): bit 0 `DERIVE`, bit 1 `LOCK`, bit 2 `LOAD_BEGIN`,
[5:4] `SLOT` (`cmd_slot`), bit 8 `PARENT_ROOT`, [13:12] `PARENT`
(`cmd_parent`), [19:16] `USE_MASK` (`cmd_mask`: bit 0 AES-enc, 1 AES-dec,
2 HMAC, 3 KDF-parent). More than one command bit set is refused by the
ladder (`E_BUSY`), as in `keyladder.v`. `KDF_CTX` (0x44-0x4B, WO) is
`cmd_ctx`, written before `KDF_CTRL`. `KDF_STATUS` (0x41, RO): bit 0
`BUSY`, bit 1 `DONE` and bit 2 `ERR` (both sticky until the next
`KDF_CTRL`), [7:4] `ERR_CODE` (`err_code`, the ladder's codes 1-9, which
name refusals, not key data).

`KEY_LOAD` (0x4C, WO) is the only key-load window: after a `LOAD_BEGIN`
command the host writes eight words to this one address, most significant
first, each presented as `ld_valid`/`ld_data`. There is no index, so no
address decode state carries key. It is write-only and has no readback.

`DRBG_CTRL` (0x60, WO): [1:0] `CMD` (0 none, 1 instantiate, 2 reseed,
3 generate), [26:16] `GEN_BITS`. `DRBG_STATUS` (0x61, RO): bit 0 `BUSY`,
bit 1 `DONE` (sticky until the next command), [3:2] `ERR` (`err`: 0 ok,
1 not instantiated, 2 reseed required, 3 bad size), bit 4 `SEEDED`, bit 5
`RESEED_REQUIRED`, bit 6 `ALARM_ZEROIZED`, bit 7 `BLK_VALID`. `DRBG_OUT`
(0x62-0x65, RO) is the most recent generated block, `blk_data`, zero while
`BLK_VALID` is low; reading does not consume it.

### Per-window statement: what each location can return

| Window | What a read returns |
|---|---|
| `STATUS`, `IRQ_*`, `FAULT_CLS`, `ZCAUSE`, `*_STATUS` | control and status flags only: slot valid/locked bits and error codes, no value derived from a key |
| `AES_DOUT` | `block_out`: AES engine output only (P-4); zero until `done` |
| `HMAC_MAC` | `mac`: HMAC engine output only (P-4); zero until `mac_valid` |
| `DRBG_OUT` | the latest generate block: DRBG engine output only (P-4); never `Key`, `V` or the seed (P-1, P-2); zero until `BLK_VALID` |
| `AES_DIN`, `AES_CTRL`, `HMAC_*` inputs, `KDF_CTRL`, `KDF_CTX`, `KEY_LOAD`, `DRBG_CTRL`, `CTRL` | write-only: a read is class 4, zero with `err_o` |

No location returns key, seed or DRBG state: the lint in
`verification/check_regmap.py` rejects a readable register wired to
`aes_key`, `hmac_key`, `root_key`, `ld_data` or a seed. The block ports
`aes_key`, `hmac_key`, `root_key` and `ld_data` each reach only an engine key
input or the ladder, never a read mux.

### Section 5 violation classes are decidable per address

| Class | Decided by |
|---|---|
| Undefined address | the address is not in the table (or an address bit above [6] is set) |
| Write to a read-only register | the address's Access is RO |
| Write while the addressed engine is busy | the address's Gate column is not `-` and that gate condition holds |
| Read of a write-only location | the address's Access is WO |

Edge cases, each decided by this table: a read of `KEY_LOAD` is class 4 (and,
being during key load, escalates per section 5 if a load is in progress); a
write to `STATUS` is class 2; an access to an unmapped offset between windows
(for example 0x1A or 0x42) is class 1; `AES_DIN` readback is class 4.

## Alternatives rejected

- **A single shared data window with a select register** (one in/out window
  that the engine select re-points): adds front-end state that decides what
  a read returns, which P-1 and P-11 would have to cover, and ties the data
  path of the engines together. Per-engine windows keep each read mux input a
  fixed engine output. This was a preference call; it follows the guidance
  in the issue, and a new record can reverse it.
- **Banked or paged windows:** the same added state.
- **Readable input windows (RW `AES_DIN`, `KDF_CTX`):** extra read paths with
  nothing to verify; the input is write-only and a read is a class 4 fault.
- **Indexed key-load window (eight addresses):** eight decoded write
  addresses for a value that is only ever streamed; the single `KEY_LOAD`
  address matches `ld_valid`/`ld_data`.
- **A DRBG output FIFO for the full 1024-bit request:** `drbg_top` has no
  back-pressure on `blk_*`, so a multi-block request needs 1024 bits of
  buffering behind the bus. Rejected for v1: see Consequences.
- **Byte-addressed offsets:** 0005 fixes a word-addressed bus.

## Consequences

- **Bus generate size is limited to 128 bits in v1.** `drbg_top` streams
  blocks with no ready, and `DRBG_OUT` holds one block. The top level treats
  `GEN_BITS` above 128 as `DRBG_STATUS.ERR` = 3 (bad size) without starting
  the core; the DRBG's own 1024-bit limit is unchanged and remains tested at
  the block. Lifting this needs a result buffer and a new record. This does
  not touch the reseed interval (2^16 requests).
- The top level (#87) holds control state not in the blocks: the sticky
  `IRQ_PEND`, `FAULT_CLS`, `ZCAUSE` and `DONE`/`DENY` bits, `IRQ_MASK`, the
  latched `HMAC_MSG_CTL`, and the message-word serializer. None of it holds
  key material, so the P-1 non-interference check covers it as non-key state.
- HMAC keys longer than 32 bytes (RFC 4231 cases 6 and 7) are reachable only
  at the block level through `key_long`, not from the bus.
- The "second violation within one operation" escalation in section 5 is
  observed through `FAULT_CLS` and `ZCAUSE` bit 2; this record does not
  define "operation" more tightly than section 5 does. #87 states that
  definition against the bus front end.
- A passing lint is a table-consistency claim only. It is not a security
  claim; P-1..P-4 and P-11 are separate properties.
