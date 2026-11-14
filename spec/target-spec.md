# Target specification

Status: **ratified for v1** (decision records 0002-0008). Changing a row
requires a new decision record.

Verification-method vocabulary: **KAT** = published known-answer vectors
(FIPS 197, FIPS 180-4, FIPS 198-1, SP 800-38A/SP 800-90A example data) run in
cocotb + Icarus; **TB** = cocotb directed/random testbench; **FORMAL** =
SymbiYosys property, depth stated in `key-isolation-properties.md`;
**STA** = `klt sta` at a named liberty corner; **SYNTH** = Yosys area/cell
report. A correct KAT is a correctness claim only.

Liberty corners: the `sky130_fd_sc_hd` set is `tt_025C_1v80`,
`ss_100C_1v60`, `ss_n40C_1v60`, `ff_n40C_1v95`, `ff_100C_1v95` (plus the
`tt_100C_1v80` and `ss_025C_1v80` PVT points where the flow provides them).
The **binding corner** for setup is `ss_100C_1v60` (slow process, high
temperature, low voltage); for hold it is `ff_n40C_1v95`. Both are stated as
expectations, to be confirmed by the first STA run. **No timing number below
has been measured.** Every timing row is "target, unmeasured".

## 1. AES

| Item | Target | Fallback | Stretch | Verification |
|---|---|---|---|---|
| Key size | AES-128 | AES-128 | AES-256 | KAT FIPS 197 App. B/C.1 (C.3 for stretch) |
| Direction | encrypt + decrypt | encrypt only (the DRBG and CTR-style use need only encrypt) | - | KAT, encrypt and decrypt vectors |
| Datapath | one round per cycle, 128-bit state (0004) | 32-bit column-serial datapath | - | TB equivalence to golden model; STA |
| Modes in hardware | ECB core only; CTR/CBC composed by the DRBG/software around it | ECB core only | CTR block wrapper | KAT SP 800-38A F.1 (ECB) |
| Key schedule | on the fly, one round key per cycle, from a key slot | stored round keys (larger, more key-bearing flops) | - | KAT; FORMAL: round keys never reach the bus |
| Latency per block | 11 cycles (10 rounds + load) | 44 cycles (fallback datapath) | - | TB cycle count; 220 ns at 50 MHz, target unmeasured |

Fallback consistency: "encrypt only" removes only the inverse cipher. The
DRBG uses only the forward cipher, so it is unaffected by the fallback.
GCM and CBC-MAC modes are not in hardware.

## 2. SHA-256 and HMAC-SHA-256

| Item | Target | Fallback | Stretch | Verification |
|---|---|---|---|---|
| Hash core | SHA-256, one round per cycle | SHA-256, two cycles per round | - | KAT FIPS 180-4 (abc, 448-bit, million-a) |
| Message length | up to 2^32 bytes per message (32-bit byte counter) | 2^16 bytes | 2^61 bytes | TB boundary lengths 55, 56, 63, 64, 119 |
| Padding | in hardware (length counter + final-block logic); software supplies bytes and a last-byte flag | in software | - | KAT incl. padding boundary lengths |
| HMAC | HMAC-SHA-256 (FIPS 198-1); key taken from a key slot | SHA-256 only | - | KAT RFC 4231 cases 1-4, 6, 7 |
| HMAC key handling | key selects a slot; the key is never a bus value and never readable. Software-supplied (bus) keys are accepted only into a write-only slot | slot-only | - | FORMAL P-3, P-5 |
| Latency per block | 65 cycles (64 rounds + load); 1.3 us at 50 MHz | 129 cycles | - | TB; STA target, unmeasured |

## 3. Key ladder

| Item | Target | Fallback | Stretch | Verification |
|---|---|---|---|---|
| Root key | 256-bit input port, `root_key[255:0]`, plus `root_key_valid`; v1 assumption in 0007 | same | - | TB; FORMAL P-1 |
| KDF | SP 800-108 counter mode, PRF = HMAC-SHA-256, fixed layout in 0003 | same, one slot | AES-CMAC counter-mode variant | KAT: published SP 800-108 HMAC-SHA-256 counter-mode vectors where available, else golden-model cross-check (#5) |
| Derived slots | 4 (`slot[0..3]`), 256-bit each | 1 | 8 | TB; FORMAL P-2 |
| Slot permissions | per slot, a use-mask over engines {AES-enc, AES-dec, HMAC, KDF-parent}, set at derivation, immutable until zeroize | one global mask | - | FORMAL P-5, TB |
| Lock bits | per slot `lock`: once set, derivation into the slot and mask change are refused until zeroize/reset | none | - | FORMAL P-6 |
| Slot visibility | write-only or never bus-visible; no read path of any kind | same | - | FORMAL P-1, P-2 |

## 4. DRBG

| Item | Target | Fallback | Stretch | Verification |
|---|---|---|---|---|
| Construction | SP 800-90A CTR_DRBG, AES-128, derivation function **yes** (0002) | same | prediction-resistance mode; AES-256 | KAT: SP 800-90A CTR_DRBG AES-128 with df example vectors |
| Seed | 16 conditioned 32-bit words (512 bits), df-compressed to 256 bits | same | - | TB vs golden model |
| Reseed | 8 conditioned words (256 bits) | same | - | TB |
| Reseed interval | 2^16 generate requests; max 1024 bits per request | 2^12 requests | - | TB, FORMAL P-8 |
| TRNG gated / alarm | seeding and reseeding **stall** while `gated`; on `alarm` the seed buffer and DRBG state are zeroized; generate refused until reseeded (details: `trng-interface.md`) | same | - | FORMAL P-9; TB (the `gated` stall has no formal property) |
| Output before seed | never; `generate` returns an error status and no data until instantiated | same | - | FORMAL P-7 |
| Seeding claim | "seeded from the sibling's conditioned output at its stated operating point". Entropy is provisional until silicon. | | | - |

## 5. Lifecycle and faults

States: `RESET` -> `UNSEEDED` -> `READY` (DRBG seeded, keys derivable) ->
`RESEED_REQUIRED` (interval hit or TRNG gated while seeded) ->
`ALARM_ZEROIZED` (terminal until recovery) . `FAULT_ZEROIZED` on a bus
protocol violation.

| Event | Zeroizes | Next state | Verification |
|---|---|---|---|
| Reset (`rst_n`) | all key slots, DRBG `Key`/`V`, seed buffer, AES/HMAC working registers, KDF scratch | `RESET` -> `UNSEEDED` | FORMAL P-10 |
| TRNG `alarm` (synchronized) | **every** key slot, DRBG state, seed buffer, working registers | `ALARM_ZEROIZED` | FORMAL P-9 |
| Bus protocol violation (access to an undefined address, write to a read-only register, write while the addressed engine is busy, read of a write-only location) | none of the key slots by default; the offending operation is refused and `FAULT` status is set. A second violation within one operation, or any violation during key load, zeroizes all slots | `FAULT_ZEROIZED` when it zeroizes | TB, FORMAL P-11 |
| TRNG `gated` (no alarm) | seed buffer only; keys and DRBG state kept | stall; `RESEED_REQUIRED` if it persists | TB |
| Software `ZEROIZE` command | all of the above | `UNSEEDED` | TB, P-10 |

Recovery from `ALARM_ZEROIZED`: the TRNG alarm must be cleared at the source
(the internal sequencer writes the sibling's W1C `ALARM` register after the
zeroize completes, and the sibling re-runs its start-up test), then the
block re-enters `UNSEEDED`. Derived keys are re-derived from the root key
port; the DRBG is re-instantiated.

Debug: **no debug path exists** in v1: no key readback, no scan-out of key
flops, no test-mode bus. Scan insertion is not performed in v1 (a scan chain
through a key flop would open a path to the key); see 0008 for what
changes if it is ever added. Verification: FORMAL P-12 (netlist).

## 6. Register interface

| Item | Target | Fallback | Stretch | Verification |
|---|---|---|---|---|
| Bus | Wishbone-classic-class single-cycle-handshake slave (`cyc/stb/we/adr/dat_i/dat_o/ack/err`), 32-bit data, word-addressed (0005) | simple valid/ready handshake | AXI4-Lite | TB protocol checker |
| Width | 32-bit | same | - | TB |
| Status model | `STATUS` register (state, busy, error, per-slot valid/locked, TRNG gated/alarm mirrors, seeded flag); one level-sensitive `irq` output = (done or error or alarm) & mask | polled only | per-source irq | TB |
| Key data | no register ever returns key, seed or DRBG state | same | - | FORMAL P-1..P-4 |

The register map (offsets, access types, `STATUS` layout, key-load window) is
decision record 0009.

## 7. Timing and area

All rows are **target, unmeasured**.

| Item | Target | Fallback | Stretch | Corner | Verification |
|---|---|---|---|---|---|
| Core clock | 50 MHz (20 ns) | 25 MHz | 100 MHz | setup binds at `ss_100C_1v60`; hold at `ff_n40C_1v95`; must also close at all other `sky130_fd_sc_hd` corners | STA via `klt sta`, every corner |
| AES-128 block latency | 11 cycles = 220 ns | 44 cycles | - | `ss_100C_1v60` | TB cycles; STA |
| SHA-256 block latency | 65 cycles = 1.3 us | 129 cycles | - | `ss_100C_1v60` | TB cycles; STA |
| Area budget | <= 0.50 mm^2 core at 40 % utilization (placeholder budget, to be re-set from the first SYNTH report; not a result) | 0.75 mm^2 | - | `tt_025C_1v80` for cell area | SYNTH, P&R report |
| Signoff | DRC + LVS clean | - | - | n/a | `klt drc`, `klt lvs` |

The TRNG-side clock is 50 kHz and is not part of this timing table; its
crossing is in `trng-interface.md`.

## 8. Not claimed

No certification, validation or side-channel claim is made, and none is
implied by a passing test. Side-channel countermeasures are out of v1 scope
(0008). Entropy is not claimed beyond the sibling's own provisional status.
