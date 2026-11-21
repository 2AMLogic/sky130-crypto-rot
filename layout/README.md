# layout

`lvs/common/` holds files vendored byte-identical from `2AMLogic/sky130-modexp`
at the commit pinned in [`reuse.lock.json`](../reuse.lock.json); do not edit
them here. Adoption decisions: [`spec/decision-records/0001-modexp-tooling-adoption.md`](../spec/decision-records/0001-modexp-tooling-adoption.md).

`place-and-route.json` is the committed `klt place-and-route` request for
the crypto_rot_top gate-level netlist (issue #295): PDN preset `sky130hd` +
tap cells, no scan insertion per `spec/target-spec.md` section 5, target
stage `route`. It is driven by
[`flow/pnr/crypto_rot_top/run.sh`](../flow/pnr/crypto_rot_top/run.sh) —
see that directory's README for the stage-bounded through-CTS invocation,
the guarded full-route contract, and the record the CTS run writes. No
routed artifact is committed yet: the detailed route and the GDS/DEF under
this directory are #47's, and until they land T1 item 2 stays `unmet`.

klt writes per-run scratch under `layout/.klt/` (gitignored) when the
committed request itself is run; the derived stage-bounded and batch
requests scratch under `flow/build/` instead.
