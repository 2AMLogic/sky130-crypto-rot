# Interface to `sky130-trng`

Pinned: `2AMLogic/sky130-trng` @ `f44ee72d42056fa2ab531f3100d4a4f4dca318e8`
(see [`../reuse.lock.json`](../reuse.lock.json)). Everything below was read
from `digital/rtl/trng_digital.v` at that commit
([blob](https://github.com/2AMLogic/sky130-trng/blob/f44ee72d42056fa2ab531f3100d4a4f4dca318e8/digital/rtl/trng_digital.v)),
with `digital/README.md` and `digital/model/params.py` at the same commit.
This document specifies **this block's side** only. It does not redesign the
TRNG, its health tests or its conditioner, and it claims nothing about
entropy beyond the sibling's own provisional status.

## 1. Ports of `trng_digital` at the pin

| Signal | Dir (from TRNG) | Width | Clock domain | Meaning / protocol |
|---|---|---|---|---|
| `clk` | in | 1 | 50 kHz sample clock | all TRNG state, including its register bus, is in this domain |
| `rst_n` | in | 1 | async | asynchronous, active low |
| `raw_bit`, `raw_valid` | in | 1, 1 | `clk` | raw tap from the analog section; not this block's |
| `bus_addr` | in | 4 | `clk` | word address |
| `bus_we`, `bus_re` | in | 1, 1 | `clk` | write / read strobes. **A read of `DATA` or `RAW_DATA` pops a FIFO** |
| `bus_wdata` | in | 32 | `clk` | |
| `bus_rdata` | out | 32 | `clk` | registered, valid the cycle after `bus_re` |
| `out_data` | out | 32 | `clk` | head of the selected FIFO; `0` when `out_valid` is low |
| `out_valid` | out | 1 | `clk` | selected FIFO non-empty |
| `out_ready` | in | 1 | `clk` | pop when `out_ready && out_valid` at a rising edge |
| `alarm` | out | 1 | `clk` | OR of RCT, APT, start-up alarms; **sticky until a W1C write to `ALARM`** |
| `gated` | out | 1 | `clk` | `alarm \| ~startup_done` |
| `startup_done` | out | 1 | `clk` | high after 1024 consecutive clean samples; drops again on any new health failure |

Facts the design depends on, as read at the pin:

- `CTRL` (word 0): `[0]` EN, `[1]` OUT_MODE (0 raw, 1 conditioned), `[2]`
  SOFT_RST. Changing OUT_MODE flushes the conditioner and both FIFOs.
- The stream port carries the **raw** FIFO when OUT_MODE = 0 and the
  **conditioned** FIFO when OUT_MODE = 1. The raw path is never gated.
- The conditioner absorbs only while ungated; on a newly raised failure the
  conditioned FIFO and partial CRC are flushed in the same cycle. So a
  conditioned word in the FIFO was assembled entirely from ungated samples.
- Both FIFOs are 4 words deep. A word completed into a full FIFO is
  **dropped** and `RAW_OVF`/`COND_OVF` is set in `STATUS`.
- Conditioner: non-vetted CRC-32 LFSR, 256 raw bits -> one 32-bit word
  (`COND_BITS = 256`, `K = 8`).
- `alarm` pin cutoffs `C_RCT = 81`, `C_APT = 824`, window 1024 are
  provisional (evaluated at H = 0.5, a design target, not a measurement).

## 2. Operating point used for the arithmetic

Stated by the sibling, not measured here: 50 kHz sample clock, 50 kbps raw
(one raw bit per sample clock, i.e. `raw_valid` high every cycle),
conditioned word every 256 raw bits.

| Quantity | Arithmetic | Value |
|---|---|---|
| Conditioned word period | 256 bits / 50 kbps | 5.12 ms |
| Conditioned throughput | 32 bits / 5.12 ms | 6.25 kbps |
| Start-up test | 1024 samples / 50 kHz | 20.48 ms |
| First seed (16 words) | 20.48 ms + 16 x 5.12 ms | **102.4 ms** after `EN` with no failure |
| Reseed (8 words) | 8 x 5.12 ms | 40.96 ms |
| Each failure restarts start-up | | +20.48 ms minimum |

All values are provisional and hold only at the sibling's stated point.
Acceptability: a ~0.1 s first-seed time at boot and ~41 ms per reseed are
acceptable for a root of trust (no streaming-rate requirement); the interval
policy (2^16 requests between reseeds) means the TRNG rate does not bound
generate throughput. If the sibling's rate changes, only these two rows and
decision record 0006's word counts change.

## 3. This block's side

### 3.1 Clock-domain crossing (decision 0006)

The 50 kHz `clk` is an **observed signal** in the core clock domain (50 MHz,
1000:1). The core never uses it as a clock.

1. `clk` passes a 2-flop synchronizer into the core domain; a rising-edge
   tick `t_rise` and a falling-edge tick `t_fall` (one core cycle each) are
   derived from the synchronized copy.
2. All TRNG outputs (`out_data`, `out_valid`, `gated`, `startup_done`,
   `alarm`) change only just after a TRNG rising edge, so they are stable for
   about half a sample period (10 us = 500 core cycles) around `t_fall`. The
   core samples them **only on `t_fall`**, all in the same core cycle. This
   makes the sampled set coherent and gives a multi-cycle constraint for
   STA: TRNG-output flops -> core capture flops constrained as a half-period
   path in the sample domain (`set_multicycle_path`/`set_false_path` as the
   flow supports; if the flow cannot express it, that is a tool gap, filed
   generically).
3. Core -> TRNG signals (`out_ready`, `bus_*`) are generated so they change
   only on `t_fall` and are held across the next TRNG rising edge, then
   cleared on the following `t_fall`. They are therefore stable well away
   from the sampling edge. A pop is exactly one sample period of
   `out_ready`, so exactly one word moves.
4. `alarm` additionally has its own 2-flop synchronizer feeding the
   zeroize logic directly, so zeroization does not wait for a `t_fall`.
   `alarm` is level and sticky at source, so no pulse can be missed.
   Worst-case latency from the alarm rising to zeroize asserted: 2 core
   cycles of synchronization, one cycle to register. Zeroize itself takes
   one cycle (parallel clear; property P-9).
5. `rst_n` to the TRNG: asserted asynchronously, released synchronously to
   the sample-domain rising edge via the same `t_rise`-aligned release.

Rejected: an asynchronous FIFO (area for 6.25 kbps of payload); treating
`clk` as the core clock (not possible: core runs at 50 MHz).

### 3.2 Register bus of the TRNG: internal only

The TRNG register bus is driven by a small sequencer inside this block and is
**not** bus-visible to the host. A host read of the sibling's `DATA` would
return seed words, which is key material by this block's definition.

The sequencer's allowed transactions (all writes, all via 3.1 point 3):

| Write | Purpose |
|---|---|
| `CTRL = EN \| OUT_MODE` (`0b011`) | enable, select conditioned stream; done once after reset |
| `CTRL.SOFT_RST` | after an alarm, before re-enabling |
| `ALARM = 0b111` (W1C) | clear sticky alarms, only after zeroize has completed |

`bus_re` is held low always. `RAW_DATA` is never read, never routed.
(Reading `ID` at boot to check the integration is a stretch item and would
need a read-capture path; not in v1.)

### 3.3 Mode and word count (decision 0006)

**Conditioned mode** (OUT_MODE = 1). A seed is **16 words** (512 bits); a
reseed is **8 words** (256 bits). The raw stream is not used. Whether to
instead take the raw stream through a vetted conditioner here is recorded in
0002 (not adopted in v1; the reasoning and what would change are there).

### 3.4 Gating rules

Sampled coherently at `t_fall`:

| Condition at `t_fall` | Rule |
|---|---|
| `gated = 1` | do not pop; do not accept `out_data`; the in-progress seed buffer is **discarded** (a seed is words from one ungated epoch) and collection restarts from word 0 |
| `startup_done = 0` | same as `gated`; seeding does not begin before `startup_done` |
| `alarm = 1` | as `gated`, plus zeroize everything (target-spec section 5); sequencer clears the alarm only after zeroize |
| `out_valid = 1`, `gated = 0`, `alarm = 0`, `startup_done = 1` | accept `out_data`, pulse `out_ready` for one sample period (3.1 point 3), append to the seed buffer |
| DRBG `RESEED_REQUIRED` and `gated = 1` | `generate` is refused; no output. State persists until a clean reseed |

The core qualifies `out_valid` itself and never relies on the sibling having
masked it (the sibling masks by flushing; this block does not depend on it).
Never accept a word on a sample where `gated` was high at either the
previous or the current `t_fall`.

FIFO overflow (4 words): the core drains at one word per sample period when
collecting, faster than the 5.12 ms word rate, so overflow is not expected;
`COND_OVF` is not observable (no bus reads). A dropped word only lengthens
collection; it cannot corrupt a seed. Recorded as an accepted
consequence.

## 4. Gaps found in the sibling at this pin

None filed. Observations that are not defects: (a) the stream port is not
qualified by `gated` and relies on the flush-on-failure behavior, which this
block does not depend on; (b) `ID` readback needs a read path this block
does not build in v1. If either is later judged a defect or requirement, it
is filed on `2AMLogic/sky130-trng`, not worked around here.
