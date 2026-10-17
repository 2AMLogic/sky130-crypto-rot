# 0004 - AES datapath: 128-bit iterative round, key schedule on the fly

Status: Accepted. Date: 2026-10-17.

## Context

Target is AES-128 at 50 MHz; encrypt-only is the fallback; AES-256 is a
stretch that must not drive architecture before the target closes.

## Decision

One full round per clock over a 128-bit state, with the round key computed on
the fly from the previous round key (one key-expansion step per cycle).
Latency 11 cycles per block (1 load + 10 rounds). 16 S-boxes for SubBytes
and 4 for the key schedule, as combinational LUT logic.

Fallback if 50 MHz does not close at the binding corner (`ss_100C_1v60`):
a 32-bit column-serial datapath (4 S-box lanes shared, 44 cycles per
block). The 128-bit-wide round is the larger and faster choice and has the
simplest control; the fallback is chosen on timing evidence only.

On-the-fly schedule rather than stored round keys: fewer key-bearing
flops (one 128-bit round-key register versus eleven), which shrinks the
set of registers the zeroize and isolation properties must cover (P-9, P-10).
Decryption with an on-the-fly schedule needs the last round key first; the
engine runs a forward key-expansion pass (10 cycles) before decrypt, so
decrypt latency is 21 cycles. This is acceptable (decrypt is not on the
DRBG path).

AES-256 (stretch) would extend the schedule to 14 rounds and 256-bit key
state; the datapath width is unchanged, so choosing 128-bit rounds does not
foreclose it.

## Alternatives rejected

- Unrolled (combinational 10 rounds): area and fan-out far past budget, no
  clock-rate need at 50 MHz.
- 8-bit byte-serial: smallest, but 160+ cycles per block with no area
  pressure in the stated budget; wasteful for hash-heavy and DRBG use.

## Consequences

Cycle counts in `target-spec.md` follow from this record; they are cycle
counts of the intended design, to be confirmed by testbench, not results.
