# Environment

This document records the pinned tool and PDK versions this repo's evidence
records are produced against, and how to reproduce that environment from a
clean checkout. Records under `verification/records/` cite these versions; if
you re-pin anything here, mint fresh records rather than editing old ones
(records are append-only).

The structure and the starting pins are taken from the same-PDK digital
sibling `2AMLogic/sky130-modexp` (`docs/environment.md` and
`scripts/setup-env.sh` at `18f4d8fd5e104f64550817a5468f262c159f734f`), each
re-resolved live on 2026-10-17 rather than copied blind (see "Re-verification").

## Reproduce the smoke run

```bash
./scripts/setup-env.sh       # once; idempotent
./flow/smoke/run.sh          # cocotb + Icarus on the RTL, then klt synthesize
```

`./flow/smoke/run.sh --record` additionally writes a record under
`verification/records/smoke-synthesis-sim/records/`.

## Provisioning: `scripts/setup-env.sh`

Creates `.venv`, installs `klayout-tools` (`klt`), `cocotb` and `ciel` into it
at the pins below, installs the pinned **Yosys/ABC build** into it and
verifies it by content, fetches the pinned `sky130A` PDK via `ciel` into
`${PDK_ROOT:-~/.ciel}` and checks that tree's `SOURCES` names the pinned
`open_pdks` commit, then checks `iverilog` and `openroad`. A missing tool is
reported with an install pointer, never a traceback. It writes only into
`.venv` and the PDK root (never `~/.local/*` or apt) and is safe to re-run.

`yosys` is deliberately **not** taken from `$PATH`: the script exposes the
pinned build as `.venv/bin/yosys`, and `flow/smoke/run.sh` puts `.venv/bin`
first on `$PATH`. `yosys -V` names only the Yosys version, not the embedded
ABC mapper, so the pin is checked by the sha256 of `yowasp_yosys/yosys.wasm`.

If the system Python lacks `venv`/`ensurepip` (Debian/Ubuntu without
`python3-venv`), the script falls back to `uv venv --seed`; without either it
stops with a pointer.

## Pinned versions

| Component | Pinned to | Resolved via |
|---|---|---|
| `klayout-tools` (`klt`) | git revision [`dac2b5daceb69a2068d9d2ee190d7afe37b29af7`](https://github.com/2AMLogic/klayout-tools/commit/dac2b5daceb69a2068d9d2ee190d7afe37b29af7) | `pip install "klayout-tools @ git+https://github.com/2AMLogic/klayout-tools@dac2b5daceb69a2068d9d2ee190d7afe37b29af7"` (what `scripts/setup-env.sh` runs) |
| Yosys + its embedded ABC | PyPI `yowasp-yosys==0.68.0.0.post1208`, verified by content: `yowasp_yosys/yosys.wasm` = `sha256:e37a7e65e3fa4efbbd64a9c1b0e906be16cdc6c4d5273109d17537f78449f38c` | `pip install "yowasp-yosys==0.68.0.0.post1208"` into `.venv`, then `.venv/bin/yosys -> yowasp-yosys`; the provision **fails** if the digest does not match |
| `sky130A` PDK | `open_pdks` commit `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`, library `sky130_fd_sc_hd` | `pip install ciel==2.6.1`, then `ciel enable --pdk-root ~/.ciel --pdk-family sky130 -l sky130_fd_pr f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`; fails if the tree's `SOURCES` names another revision |
| `ciel` | 2.6.1 | `pip install ciel==2.6.1` into `.venv` |
| `cocotb` | 2.1.0 | `pip install cocotb==2.1.0` into `.venv` |
| Python | <= 3.13 (cocotb 2.x refuses to build on 3.14+) | `scripts/setup-env.sh` picks the newest of `python3.13` ... `python3.10`, `python3` on `$PATH` |

`scripts/setup-env.sh`'s pin block and this table must change together.
`verification/check_pins.py` (modexp's checker, vendored by issue #6 and wired
into lint by issue #7) fails when they disagree; until then it can be run from
a temporary copy of modexp's file. The Re-verification and not-pinned notes
below name versions on purpose and are not checked.

## Tools not pinned by `setup-env.sh`

| Tool | Status |
|---|---|
| Icarus Verilog | host install (`iverilog`); the version is recorded in each record. Observed: 13.0 |
| OpenROAD | host install; only checked, not provisioned. Not used by the smoke flow. Observed: `26Q3-1510-g6cb3f2b704` |

These are not content-pinned. A re-pin to a container digest or a built
revision belongs with the first issue that depends on OpenROAD (place and
route, STA).

## Re-verification (2026-10-17)

- `klt` `dac2b5da` resolves on `2AMLogic/klayout-tools` (committed
  2026-09-23). `main` has since moved to `267ea83a`; the pin is kept because
  it is the revision sky130-modexp's current records run against, and the
  smoke flow passes on it. PyPI `klayout-tools` is 0.7.0.
- `yowasp-yosys==0.68.0.0.post1208` still installs and its `yosys.wasm`
  digest matches. PyPI has 0.70.0.0.post1259; not adopted (no reason to move).
- `ciel` is pinned at 2.6.1 (PyPI has 3.1.0, not adopted).
- `cocotb` is pinned at 2.1.0, which is what resolved; modexp's doc says 2.0.1.
  The smoke test passes on 2.1.0.
- `open_pdks` `f6eeac7d` matches the `SOURCES` file of the installed tree.

## Smoke flow scope

`flow/smoke/` holds a registered 8-bit adder, a cocotb test, and `klt`
requests. `klt sta` is not run: it consumes a routed DEF, so it needs
place-and-route, which is out of scope for this bring-up.
