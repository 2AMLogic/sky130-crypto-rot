# crypto_rot_top place-and-route flow

`layout/place-and-route.json` (one committed `klt place-and-route` request:
PDN preset `sky130hd` + tap cells, **no scan insertion** per
`spec/target-spec.md` section 5) plus this directory's driver place the
committed gate-level netlist
(`verification/rtl/crypto_rot_top/netlist/crypto_rot_top_synth.v`) on
`sky130_fd_sc_hd` at `tt_025C_1v80`. Issue #295 landed the flow with a
**through-CTS record**; the detailed route is #47's.

## Prerequisites

`./scripts/setup-env.sh` (venv klt, pinned yosys, sky130A PDK) and an
`openroad` binary on `$PATH` — a host install; see
[`docs/environment.md`](../../../docs/environment.md) (not content-pinned;
each record names the build it ran from the response's `engine_version`).

## Invocations

```sh
./flow/pnr/crypto_rot_top/run.sh --through-cts          # guard + floorplan -> place -> CTS
./flow/pnr/crypto_rot_top/run.sh --through-cts --record # + record under verification/records/crypto-rot-top-pnr/
./flow/pnr/crypto_rot_top/run.sh --record               # full-route contract: --backend batch, refused on
                                                        # a pin without single-unit batch (klt 0.8.0 is one)
./flow/pnr/crypto_rot_top/run.sh --record --local-full-route  # deliberate manual local route (~6 h wall)
```

The stale-netlist guard (`check-fresh.sh`) runs **first** on every path
that starts OpenROAD, and the netlist hash it verified binds every artifact
of the run. `--through-cts` derives the stage bound (`target_stage: "cts"`)
from the committed request into build scratch — the derived document's
netlist path is re-anchored and hash-verified to name the committed bytes.
Bare `--record` is the **full-route** contract for #47: an explicit
`--backend batch` with `batch.job_timeout_s` (default 36000 s) sized above
the measured route time (4.5–6 h wall estimated from two unfinished runs,
plus ~25 min pre-route). Until the klt pin can dispatch a single unit to
batch (2AMLogic/klayout-tools#6897; thread control is #6898) it refuses —
no local route starts by default; `--local-full-route` is the explicit
manual opt-in. A completed route stages its GDS/DEF/post-route netlist and
response under `layout/`; the route record and item-2 attestation remain
#47's.

## Records

`--through-cts --record` writes an append-only record under
`verification/records/crypto-rot-top-pnr/`: placed-instance count (read
from the run's own CTS DEF), die/core area and utilization against the
spec section 7 placeholder budget row (reported, never edited), the
netlist hash, and the tool/PDK pins. Every timing figure in it is labelled
a pre-route estimate; the section 7 timing rows stay "target, unmeasured"
until STA (#50). No routed-GDS claim: T1 item 2 stays `unmet`.
