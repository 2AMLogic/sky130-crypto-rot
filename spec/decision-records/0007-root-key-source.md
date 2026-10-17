# 0007 - Root key arrives on a port

Status: Accepted (assumption). Date: 2026-10-17.

## Decision

The root key is a 256-bit input port `root_key[255:0]` with a qualifier
`root_key_valid`, supplied by the integrator. v1 designs no fuse, OTP or
other non-volatile storage and makes no claim about how the integrator
protects the port.

Rules this block applies to the port: the key is read into a hold register
only while `root_key_valid` is high and the block is in a state that permits
derivation; the hold register is key material for all properties and is
zeroized with the slots; no path routes `root_key` to any output, status or
register (P-1, P-2). `root_key_valid` low zeroizes the held copy.

## What would change with fuses/OTP

A storage macro would sit behind the port: its read path becomes part of
the isolation boundary (P-1..P-3 must cover the macro's output), burn/read
control and the lifecycle state (blank/provisioned/locked) join section 5
of the target spec, and the macro's own side-channel and tamper behavior
become requirements.
