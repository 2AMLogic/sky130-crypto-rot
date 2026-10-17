# Key-isolation properties

Each property is a statement about **every path**, not a test. Each is
marked:

- **N** - netlist-provable: stated as a SymbiYosys property, proven on RTL,
  and re-proven on the Yosys-synthesized `sky130_fd_sc_hd` netlist (the
  property must hold on the mapped design, not just be carried over by an
  RTL equivalence argument).
- **R** - RTL-provable only: provable on RTL; the netlist re-proof is not
  expected to be tractable with the open flow at v1 (reason given).
- **O** - open: no proof method is committed to yet; the open question is
  stated.

"Proven" always carries a bound: a BMC depth, or an induction claim with its
inductive strengthening. A property is not claimed beyond the depth it was
run at. Key material means: root key, derived slot contents, AES round keys,
HMAC `K0`/ipad/opad states, KDF intermediate values, DRBG `Key`/`V`, and the
seed buffer.

| # | Property | Mark | Method and bound |
|---|---|---|---|
| P-1 | For every bus input sequence, `dat_o` is a function of non-key state only: no bus read returns any bit that depends on key material. Stated as a 2-trace non-interference check: two runs that differ only in key material produce identical `dat_o`/`ack`/`err`/`irq` sequences | N | SymbiYosys, 2-copy product, BMC at the depth of the longest operation (>= one full HMAC block, ~70 cycles) plus k-induction on the idle state; netlist run needs Yosys to read the cell models (see Open questions) |
| P-2 | No slot has a read path: the cone of influence of every output port excludes slot flops except through the engine datapath (P-4) | N | structural cone-of-influence check in Yosys on the netlist, plus P-1 |
| P-3 | The HMAC/AES key input is selected only from a slot or a write-only load register; no bus-readable register feeds a key input | N | structural + P-1 |
| P-4 | Engine outputs (ciphertext, MAC) are released only to the permitted consumer: a slot's use-mask gates which engine may read it, and ciphertext/MAC reaches the bus only through the defined result registers | R | RTL property on the arbitration logic; the permission-mask semantics ("which output is allowed to leave") are not a pure non-interference property, so a netlist re-proof is only of the mask logic, not of the cryptographic release |
| P-5 | A slot is used only by engines whose use-mask bit is set at the time of use | N | assertion on the engine-select mux, BMC depth 16, induction |
| P-6 | A locked slot cannot be written or have its mask changed until zeroize/reset | N | assertion, induction |
| P-7 | The DRBG never emits output before it is seeded: `generate` output valid implies `seeded` and not `reseed_required` | N | assertion, induction on the state machine |
| P-8 | After the reseed interval is reached, `generate` produces no output until a reseed completes | N | assertion, induction; counter width proven by induction, not by running 2^16 steps |
| P-9 | A synchronized TRNG `alarm` zeroizes every key slot, DRBG `Key`/`V`, seed buffer and working register within the stated number of core cycles, and holds them zero while `alarm` is asserted | N | assertion with bounded response (<= 4 cycles after the synchronizer), BMC; the 2-flop synchronizer is modelled as an ordinary register chain at 50 MHz (clock-domain timing itself is not proven formally) |
| P-10 | Reset and the software `ZEROIZE` command clear the same set of registers as P-9 | N | assertion over the same register list; list completeness is a review item, backed by a structural check that every key-bearing register has a clear term |
| P-11 | A bus-protocol violation never causes a state change that exposes key material, and the defined escalation (second violation, or one during key load) zeroizes all slots | R | RTL property on the bus front end |
| P-12 | The synthesized netlist contains no path from a key-bearing flop to an output port or to a scan/test structure: no scan chain, no test mux, no debug port is inserted by synthesis or place-and-route | N | structural check on the netlist: cone of influence of every output excludes key flops except through P-4 logic; scan/DFT insertion is disabled and the flow log is checked for any inserted structures |
| P-13 | Gate-level equivalence: the synthesized and placed netlists are sequentially equivalent to the RTL, so P-1..P-12 proven on one carry to the others | O | `klt equiv` with the sequential engine is available (the sibling repo uses it); whether it scales to the full design with its key schedule is unknown. If it does not, P-1..P-12 are re-run on each netlist rather than carried |
| P-14 | Key material does not leak through the TRNG interface: the sequencer never reads the sibling's `DATA`/`RAW_DATA`, and no sibling output is routed to a host-readable register | N | structural (no net from `trng_bus_re`-driven read data to `dat_o`; `bus_re` constant 0) |
| P-15 | Timing/power/electrical side channels do not distinguish key values | O | out of scope for v1 (0008). Nothing here claims side-channel resistance. |

## Open questions

1. **How far does the open formal flow go on a post-synthesis netlist?**
   P-1 as a two-trace product over a ~70-cycle HMAC block with full key
   schedule is the hard case. If SymbiYosys with the open solvers cannot
   close it at the stated depth on the mapped netlist, the property stays
   "R" (RTL) and is recorded as such with the depth actually reached.
2. **Cell models for formal.** Mapped netlists instantiate
   `sky130_fd_sc_hd__*` cells; Yosys formal needs synthesizable models of
   them (the PDK's simulation models are not all formal-friendly). If the
   flow cannot do this, that is a tool gap to be filed generically at
   `2AMLogic/klayout-tools` (or the right upstream tool) when first hit,
   described without reference to this design.
3. **Are k-induction proofs of P-1 possible without manual
   strengthening?** If not, the strengthening invariants become part of the
   recorded evidence.

Nothing above is a certification, validation or side-channel claim.
