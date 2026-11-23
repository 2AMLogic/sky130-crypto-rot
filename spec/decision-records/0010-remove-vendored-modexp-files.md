# 0010 - Remove the three vendored sky130-modexp files

Status: Accepted. Date: 2026-11-23. Issue: #134.

Supersedes only the "Adopted (3)" section of
[0001](0001-modexp-tooling-adoption.md). The twelve not-adopted files and the
upstream request (2AMLogic/sky130-modexp#211) in 0001 are unaffected.
Operator ruling: option `a` (attended session, 2026-11-23): remove all three,
keeping `tie_constants.py` only if a synthesized netlist still held bare
literals.

## Decision

The adopted set goes from three files to zero. `flow/common/tie_constants.py`,
`layout/lvs/common/expand_concat_assigns.py` and
`verification/gate-level/common/sky130_fd_sc_hd_sim_defines.v` are deleted and
the `2AMLogic/sky130-modexp` entry is dropped from `reuse.lock.json`. Each was
an interim workaround for a klayout-tools gap, none had a caller in this repo
(0001 itself made no claim that they ran here), and all three gaps are closed
at the pinned klt (`scripts/setup-env.sh`, `KLT_VERSION="0.9.2"`).

## Per-file reason and measurement

Measured 2026-11-23 at klt 0.9.2 and the pinned YoWASP Yosys 0.68.0.0.post1208.

| File | Gap | Evidence at the pin |
|---|---|---|
| `tie_constants.py` | `klt synthesize` left bare literals in the mapped netlist | `verification/rtl/aes/run.sh` (single local unit, `klt synthesize`, tt_025C_1v80) mapped `aes_core` to 30204 instances. In the resulting `aes_core_synth.v`, a search for sized literals (`[0-9]+'[bhd][0-9xXzZ]`) finds 0; `sky130_fd_sc_hd__conb_1` appears 9816 times. The "keep if bare literals survive" condition is not met. |
| `expand_concat_assigns.py` | the LVS gate-level reader rejected `assign x = { a, b };` | `klayout_tools.verilog_netlist.parse_gate_level_verilog` at 0.9.2 parses a module containing `assign w = { a, b };` without a pre-pass. |
| `sky130_fd_sc_hd_sim_defines.v` | no request field for `+define+` macros | `options.defines` exists and is used by the aes and sha256 gate-level requests. klt also checks it against `options.sdf`, which a source-file define would bypass. |

## Why remove rather than keep

The layout issues (#47, #49, #82) place netlist-rewriting helpers between
synthesis and the netlist re-proofs. Key-isolation properties are re-proven on
that netlist, so an unneeded rewriting pass is one more step the re-proof
would have to cover, for no benefit.

## Consequences

- No live text names a deleted file; the aes and sha256 request comments and
  the gate-level record bullet now state only that `options.defines` is used.
- `verification/records/` is append-only evidence and still mentions the
  files in earlier records; those are unchanged.
- This claims nothing beyond the measurements above, at one netlist (aes).
