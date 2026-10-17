# 0005 - Register bus: Wishbone-classic-class slave, 32-bit

Status: Accepted. Date: 2026-10-17.

## Decision

A 32-bit word-addressed slave with Wishbone-B4-classic style signals
(`cyc_i`, `stb_i`, `we_i`, `adr_i`, `dat_i`, `dat_o`, `ack_o`, `err_o`),
single outstanding transfer, no wait-state requirement on the master, plus a
level `irq_o`. Same clock as the core. `err_o` signals a protocol
violation (bus-fault policy in `target-spec.md` section 5): access to an
undefined address, write to a read-only register, a write while the
addressed engine is busy, or a read of a write-only location (which returns
zero with `err_o`, never data).

Rationale: open-source Wishbone interconnect and cocotb bus drivers
exist; the single-cycle handshake keeps the front end small and its
formal model simple (P-1, P-11); `err_o` gives a clean way to make
protocol violations observable and to attach the fault policy.

## Alternatives rejected

- APB: also acceptable; Wishbone chosen for the explicit `err`.
- AXI4-Lite: stretch; five channels add state to prove properties over.
- Bare valid/ready: the fallback; no error response channel, so the fault
  policy would need a status-only mechanism.

## Consequences

The bus front end is the only path from host to key logic and is the unit
P-1/P-11 are stated against. The sibling's register bus is a different,
internal-only bus (`trng-interface.md`).
