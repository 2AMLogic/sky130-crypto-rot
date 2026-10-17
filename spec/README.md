# spec

The ratified specification for `sky130-crypto-rot`. Spec changes go through
this directory with a decision record; results are never allowed to relax it.

| File | Contents |
|---|---|
| [`target-spec.md`](target-spec.md) | Every parameter group: target / fallback / stretch / verification method |
| [`trng-interface.md`](trng-interface.md) | This block's side of the `sky130-trng` interface, at a pinned commit |
| [`key-isolation-properties.md`](key-isolation-properties.md) | Numbered key-isolation properties, each marked RTL-provable, netlist-provable or open |
| [`decision-records/`](decision-records/) | One record per non-obvious choice |

Decision records here are numbered `NNNN-<slug>.md`, shared with the other
work that writes records in this directory (`0001` is the modexp tooling
record from the reuse-pin change). The pinned sibling commit lives in
[`../reuse.lock.json`](../reuse.lock.json).

No document in this directory claims certification, validation,
side-channel resistance, or full entropy. Where those words appear they
disclaim the claim.
