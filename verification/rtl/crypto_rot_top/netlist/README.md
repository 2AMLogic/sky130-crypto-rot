# crypto_rot_top -- committed gate-level netlist (T1 item 1)

The synthesized `sky130_fd_sc_hd` netlist of `rtl/crypto_rot_top.v`, committed
so the spec's netlist-marked properties (P-12 first; `spec/
key-isolation-properties.md`) are stated about a fixed artifact instead of a
regenerated one, and so the item-1 signoff inventory can bind it (issue #88).
The synthesis request itself is the pre-existing
`verification/rtl/crypto_rot_top/synth-request.json` (reused, not re-created).

| File | What it is |
|---|---|
| `crypto_rot_top_synth.v` | the netlist (114694 instances, `tt_025C_1v80`, pre-P&R). Not hand-edited: regenerate, never patch. |
| `synthesize-envelope.json` | the `klt synthesize` response of the run that produced the committed netlist (its `netlist_sha256` pins the netlist; `run_id`/scratch paths are that run's provenance, not reproducible). |
| `flow-log.ys` | the synthesis script that run recorded (a copy of the response's `run_script_path` artifact): the flow log the P-12 scan/DFT check reads. |
| `check-fresh.sh` | the freshness check: re-runs the committed request and byte-compares against the committed netlist. Exit `0` fresh, `3` stale (the `klt netlist --check` convention), other = hard error. This is the `derived` check of `manifests/inventories/item-1.json`. |

Byte-compare is sound because the flow is deterministic: two clean
`klt synthesize` runs of this request at different scratch paths produced
byte-identical netlists (pinned `klayout-tools==0.8.0`,
yowasp-yosys 0.68.0.0.post1208, sky130A `f6eeac7d`; verified 2026-11-17,
recorded in `verification/records/crypto-rot-top-netlist-formal/`).

Regenerate after an RTL edit (check-fresh prints the exact recipe on drift):

```sh
./scripts/setup-env.sh          # once: .venv with klt + pinned yosys
./verification/rtl/crypto_rot_top/netlist/check-fresh.sh   # must exit 0
# on drift: re-synthesize, copy the fresh netlist here, and refresh
# synthesize-envelope.json from the new run's response.
```

The P-12 structural proof on this netlist (and its negative controls) is
`verification/formal/crypto_rot_top/run.sh`, recorded under
`verification/records/crypto-rot-top-netlist-formal/`. No security,
certification or side-channel claim attaches to any of this: it is a
reproducibility and structure statement about one committed artifact.
