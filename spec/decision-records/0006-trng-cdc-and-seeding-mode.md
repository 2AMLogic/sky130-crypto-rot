# 0006 - TRNG interface: observed-clock CDC, conditioned seeding mode

Status: Accepted. Date: 2026-10-17. Sibling pinned at
`f44ee72d42056fa2ab531f3100d4a4f4dca318e8`.

## Decision

1. **CDC.** Observe the 50 kHz sample clock as a signal; sample all
   sibling outputs together at its falling-edge tick; generate core ->
   sibling signals on that tick so they are stable across the sibling's
   rising edge; `alarm` also takes a direct 2-flop path to zeroize logic.
   Full rules in `trng-interface.md` section 3.1.
2. **Mode.** Conditioned (OUT_MODE = 1) only; the raw path is never read.
3. **Words per seed.** 16 for instantiate, 8 for reseed (see 0002).
4. **Seeding latency.** ~102.4 ms to first seed, ~41 ms per reseed at the
   stated operating point; accepted (arithmetic in `trng-interface.md`
   section 2).
5. **Gating.** Any `gated` or `alarm` observation discards the partial seed;
   `alarm` zeroizes; generation is refused while reseed is required.

## Why this CDC

The data rate is 6.25 kbps of conditioned payload in a 1000:1 clock-ratio
crossing. Sampling at a point known to be half a sample period away from any
sibling change is simpler to reason about than an async FIFO or toggle
handshake, gives one coherent snapshot of `out_valid`, `out_data`, `gated`
and `alarm`, and the pop is by construction one word. The cost is that
the sample clock must be observable by the core (an input pin, or derived
from the core clock) and that STA needs the half-period path constraint.

## Alternatives rejected

- Async FIFO / Gray pointers: more area than the payload justifies.
- Two-flop synchronizing each signal independently: loses coherence, so
  `out_valid` and `gated` could be seen at different sample instants.
- Raw mode with an in-block vetted conditioner: see 0002.

## Consequences

Needs from integration: the sample clock reaches the core as a pin or is a
divided copy of the core clock. If integration cannot provide that, this
record is revisited. No TRNG defect was found at the pin (see
`trng-interface.md` section 4).
