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

## Reproduce the toolchain run

```bash
./scripts/setup-env.sh                  # once; idempotent
```

That provisions the environment; it does not run anything. For what to run in
it, `README.md` "Reproduce" gives the CI and cold-start commands, and
`rtl/README.md` names the `run.sh` that verifies each block. Each `run.sh`
takes `--negative-control`, and `--record` to write a record under
`verification/records/`.

The original bring-up run, on a registered 8-bit adder that has since been
retired in favour of the SHA-256 core flow, is the append-only record
`verification/records/smoke-synthesis-sim/records/20261017-214652-6edf260.md`;
its inputs are reproducible from commit `6edf260`.

## Provisioning: `scripts/setup-env.sh`

Creates `.venv`, installs `klayout-tools` (`klt`), `cocotb` and `ciel` into it
at the pins below, installs the pinned **Yosys/ABC build** into it and
verifies it by content, fetches the pinned `sky130A` PDK via `ciel` into
`${PDK_ROOT:-~/.ciel}` and checks that tree's `SOURCES` names the pinned
`open_pdks` commit, then checks `iverilog` and `openroad`. A missing tool is
reported with an install pointer, never a traceback. It writes only into
`.venv` and the PDK root (never `~/.local/*` or apt) and is safe to re-run.

`yosys` is deliberately **not** taken from `$PATH`: the script exposes the
pinned build as `.venv/bin/yosys`, and every flow driver puts `.venv/bin`
first on `$PATH` -- `flow/common/core_flow.sh` (`core_flow_setup`, sourced by
every `verification/rtl/*/run.sh`), `scripts/ci-verify.sh`,
`verification/formal/run.sh` and `verification/formal/keyladder/run.sh`.
`yosys -V` names only the Yosys version, not the embedded ABC mapper, so the
pin is checked by the sha256 of `yowasp_yosys/yosys.wasm`.

If the system Python lacks `venv`/`ensurepip` (Debian/Ubuntu without
`python3-venv`), the script falls back to `uv venv --seed`; without either it
stops with a pointer.

## Pinned versions

| Component | Pinned to | Resolved via |
|---|---|---|
| `klayout-tools` (`klt`) | PyPI [`klayout-tools==0.9.2`](https://pypi.org/project/klayout-tools/0.9.2/) (tag [`v0.9.2`](https://github.com/2AMLogic/klayout-tools/releases/tag/v0.9.2), commit `046ba74652fc`) | `pip install "klayout-tools==0.9.2"` (what `scripts/setup-env.sh` runs) |
| Yosys + its embedded ABC | PyPI `yowasp-yosys==0.68.0.0.post1208`, verified by content: `yowasp_yosys/yosys.wasm` = `sha256:e37a7e65e3fa4efbbd64a9c1b0e906be16cdc6c4d5273109d17537f78449f38c` | `pip install "yowasp-yosys==0.68.0.0.post1208"` into `.venv`, then `.venv/bin/yosys -> yowasp-yosys`; the provision **fails** if the digest does not match |
| SymbiYosys (`sby`), `yosys-smtbmc`, `yosys-witness` | shipped inside the same `yowasp-yosys==0.68.0.0.post1208` wheel (entry points `yowasp-sby`, `yowasp-yosys-smtbmc`, `yowasp-yosys-witness`); pinned by the same `yosys.wasm` digest; there is no standalone `sby` on PyPI | linked as `.venv/bin/sby`, `.venv/bin/yosys-smtbmc`, `.venv/bin/yosys-witness` by `scripts/setup-env.sh` |
| `z3` (SMT solver for `sby`) | PyPI `z3-solver==5.3.2.0`, verified by content: `.venv/bin/z3` = `sha256:c45e787b5d1a3d94079d1e83b98e23bbc884ccaf542ea38c3814f31ac2f79197` | `pip install "z3-solver==5.3.2.0"` into `.venv` (the wheel ships a native `z3` binary); the provision **fails** if the digest does not match |
| `sky130A` PDK | `open_pdks` commit `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`, library `sky130_fd_sc_hd` | `pip install ciel==2.6.1`, then `ciel enable --pdk-root ~/.ciel --pdk-family sky130 -l sky130_fd_pr -l sky130_fd_sc_hd f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`; fails if the tree's `SOURCES` names another revision |
| `ciel` | 2.6.1 | `pip install ciel==2.6.1` into `.venv` |
| `cocotb` | 2.1.0 | `pip install cocotb==2.1.0` into `.venv` |
| Python | <= 3.13 (cocotb 2.x refuses to build on 3.14+) | `scripts/setup-env.sh` picks the newest of `python3.13` ... `python3.10`, `python3` on `$PATH` |

`scripts/setup-env.sh`'s pin block and this table must change together.
`verification/check_pins.py` (run by `npm run lint`) fails when a value in the
script's pin block does not appear in the table above. The Re-verification and not-pinned notes
below name versions on purpose and are not checked.

The same checker guards the one other hand copy: the `pins` block of
`manifests/inventories/item-9.json`, which `klt signoff --attest 9` records
into the committed attestation envelope. It must name the same `klayout-tools`,
`yowasp-yosys`, `cocotb` and `ciel` versions and the same PDK revision as the
pin block. That block's `icarus-verilog` entry is not checked: Icarus is a host
install `scripts/setup-env.sh` only probes for (see "Tools not pinned by
`setup-env.sh`" below), so there is no pin to compare it against.

## Tools not pinned by `setup-env.sh`

| Tool | Status |
|---|---|
| Icarus Verilog | host install (`iverilog`); the version is recorded in each record. Observed: 13.0 |
| OpenROAD | host install; only checked, not provisioned. Consumed by `klt sta`, which shells out to it: the pre-layout setup-timing mode (`verification/rtl/aes/run.sh --timing`, `verification/rtl/sha256/run.sh --timing`, issue #178) was this repo's first committed flow that depends on it; the place-and-route flow (`flow/pnr/crypto_rot_top/run.sh`, issues #295/#47) is the second — every flow's records name the build from the response's own `engine`/`engine_version` fields. Observed: `26Q3-1510-g6cb3f2b704` (native binary on `$PATH`; no container needed — a container-wrapped `openroad` also works because the flow invokes klt from the repo root, the one tree such a wrapper mounts) |

These are not content-pinned. The deferred OpenROAD re-pin's trigger -- "the
first issue that depends on OpenROAD (place and route, STA)" -- has now
fired with the timing mode above; pinning it to a container digest or a
built revision remains its own future decision, not part of that issue.

`klt sta` does **not** need place-and-route on the pinned `klayout-tools`
0.9.2: its DEF-free `verilog` mode times a structural netlist against
liberty plus a clock constraint alone and labels the result
`geometry_source: "netlist_estimate"`. Pre-layout setup timing (issue #178)
uses that mode; routed-DEF timing still needs place-and-route and remains
out of scope (#50).

## klt re-pin (2026-11-20)

- `klt` moved from PyPI `klayout-tools==0.8.0` to PyPI `klayout-tools==0.9.2`
  (issue #294): the newer release carries `klt signoff --skip-local-only`,
  the `--attest 2 --input` mint path the T1 item-2 envelope needs
  (klayout-tools#6038) and place-and-route `--resume`. Single-unit
  `place-and-route --backend batch` is still refused by 0.9.2 (it needs at
  least two corners); publication of that capability is tracked by
  klayout-tools#6897. The records committed before this date ran on 0.8.0;
  they are append-only evidence and are not regenerated.

## klt re-pin (2026-10-27)

- `klt` moved from git revision `dac2b5da` to PyPI `klayout-tools==0.8.0`
  (issue #77). A git build reports a dev version and no longer satisfies
  `==0.8.0` (klayout-tools#2823), so the pin is the PyPI release, not a
  `git+...@<sha>` form. The old revision `dac2b5da` is what the records
  committed before this date ran on (`klt 0.6.0+gdac2b5daceb6`); they are
  append-only evidence and are not regenerated.

## Re-verification (2026-10-17)

- `klt` `dac2b5da` resolved on `2AMLogic/klayout-tools` (committed
  2026-09-23) and was the pin at this date; superseded by the re-pin above.
- `yowasp-yosys==0.68.0.0.post1208` still installs and its `yosys.wasm`
  digest matches. PyPI has 0.70.0.0.post1259; not adopted (no reason to move).
- `ciel` is pinned at 2.6.1 (PyPI has 3.1.0, not adopted).
- `cocotb` is pinned at 2.1.0, which is what resolved; modexp's doc says 2.0.1.
  The adder smoke test (since retired) passed on 2.1.0.
- `open_pdks` `f6eeac7d` matches the `SOURCES` file of the installed tree.
