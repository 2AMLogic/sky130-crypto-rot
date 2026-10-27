# rtl/trng_if

`trng_if.v` is this block's side of the interface to `sky130-trng`
(`spec/trng-interface.md`, decision records 0002 and 0006): clock-domain
crossing, coherent sampling and gating, the seed buffer, a write-only
sequencer for the sibling's register bus, and the alarm -> zeroize path.
`../drbg/drbg_top.v` ties it to `ctr_drbg` and an AES engine for the benches.
The sibling's RTL is not in this repository (`reuse.lock.json` pins it; the
benches fetch it with `verification/rtl/trng_if/fetch_trng.sh`).

Run and verify it with `verification/rtl/trng_if/run.sh` (simulation) and
`verification/formal/run.sh` (P-9). Nothing here is a security or entropy
claim; see the records under `verification/records/`.

## Behavior at `t_fall`

The sample clock (`trng_clk`, 50 kHz) is an observed signal, never a clock.
`c1`/`c2` synchronize it; `t_rise`/`t_fall` are one-core-cycle ticks from
`c2` and its delayed copy. At each `t_fall` the module samples the sibling's
`out_data`, `out_valid`, `gated`, `startup_done` and `alarm` in the same core
cycle, then:

| Condition | Action |
|---|---|
| `gated`, `~startup_done` or `alarm` (a "bad" sample) while collecting | discard the partial seed, restart at word 0 |
| collecting, `out_valid`, this sample and the previous `t_fall` sample both clean | store `out_data` as the next word, drive `out_ready` high until the next `t_fall` (one sample period: exactly one pop) |
| 16 (instantiate) or 8 (reseed) words stored | `seed_ready` high; `seed` held until `seed_release` clears it |

The previous-sample flag resets to "bad", so the first sample after reset or
a zeroize is never accepted. `out_valid` is qualified here; the sibling's
flush-on-failure is not relied on.

## Clock-domain crossings

| # | Crossing | Structure | Constraint it implies for STA |
|---|---|---|---|
| 1 | `trng_clk` into the core domain | 2-flop synchronizer (`c1`, `c2`) plus a third flop for edge detection | asynchronous input; treat as a synchronizer (false path to `c1`, or a max-delay of one core period) |
| 2 | sibling `out_data`/`out_valid`/`gated`/`startup_done`/`alarm` into the sampling logic | no synchronizer per signal: the outputs change only just after a sibling rising edge and are captured only at `t_fall`, half a sample period (10 us = 500 core cycles at 1000:1) later | sibling output flops -> core capture flops: a half-period path in the sample domain (`set_max_delay` of at most half the sample period, or a multicycle path with the capture edge at `t_fall`); a plain single-core-cycle check on these paths would be wrong in both directions |
| 3 | sibling `alarm` into zeroize | its own 2-flop synchronizer (`a1`, `a2`), `a2` feeds the registered `zeroize` | synchronizer: same constraint as row 1 |
| 4 | `out_ready`, `bus_we`, `bus_addr`, `bus_wdata` into the sibling | core flops that change only at `t_fall`, so they are stable across the next sibling rising edge and change half a period after it | core flops -> sibling capture flops: half-period path; hold: the signals must not change within the window around the sibling's rising edge, which `t_fall` timing guarantees by construction |
| 5 | `rst_n` | asynchronous assert, 2-flop synchronous release in the core domain; the sibling's `rst_n` (`trng_rst_n`) is asserted asynchronously and released on a `t_rise` tick, i.e. 2-3 core cycles after a sibling rising edge | recovery/removal on the sibling's reset pins: released far from its next edge; assert is asynchronous |

Row 2 and row 4 are the constraints a flow has to express; whether the
provisioned flow can express them was not exercised here (no STA was run for
this block). The sample-clock ratio used by the benches is 40:1 and 1000:1
(the real ratio); all values are at the sibling's stated operating point.

## Not specified, therefore not implemented

`spec/target-spec.md` section 5 says a persisting `gated` moves a seeded
block to `RESEED_REQUIRED`, but gives no persistence threshold. This module
stalls collection while gated and discards a partial seed; it does not time
`gated` out. A completed DRBG state is kept across `gated` (only an `alarm`
zeroizes it).
