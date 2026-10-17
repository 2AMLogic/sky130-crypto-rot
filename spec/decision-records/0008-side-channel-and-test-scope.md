# 0008 - Side-channel countermeasures and test structures out of v1

Status: Accepted. Date: 2026-10-17.

## Decision

Side-channel countermeasures (masking, hiding, constant-power logic,
randomized clocking) are **out of v1 scope**. This block makes no claim of
side-channel resistance, certification or validation. A passing known-answer
test says the algorithm is implemented correctly and says nothing about
leakage. The same applies to fault-injection resistance.

Scan insertion and debug ports are also out of v1: no scan chain is
inserted (it would add a path from key-bearing flops to a port, which this
block treats as a defect, P-12) and no debug interface exists.

## What would change if countermeasures were added

- AES: masked S-boxes (e.g. Boolean masking or threshold implementation)
  need fresh randomness per cycle, which comes from the DRBG or the TRNG, so
  a masked AES and the DRBG would depend on each other and on seeding order;
  area and latency grow several-fold; the golden model needs a masked
  variant; the S-box lookup assumption in 0004 changes.
- SHA-256/HMAC: masking additions and word-wise operations; HMAC key
  handling gets an explicit leakage requirement.
- Key-isolation properties: P-1's non-interference check is a
  functional-flow property; leakage needs a separate method (simulated or
  measured traces), and P-15 changes from "out of scope" to a measured
  requirement with its own evidence tier.
- Test structures: any scan or JTAG would need a locked/disabled-by-
  lifecycle design and a re-proof of P-12 with the structure present.

## Consequences

`key-isolation-properties.md` P-15 stays open and unclaimed.
