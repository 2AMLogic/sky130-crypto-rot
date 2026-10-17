# 0001 — Which sky130-modexp flow and verification tooling is adopted

- **Status:** accepted
- **Rule:** `2am/REUSE.md` (cross-cutting rule 9)
- **Pin:** `2AMLogic/sky130-modexp@18f4d8fd5e104f64550817a5468f262c159f734f`, `mode: vendored`
- **Upstream request:** 2AMLogic/sky130-modexp#211

## Decision

Fifteen candidate files were evaluated at the pinned commit. Three are vendored
byte-identical under `common/` (stamped in `reuse.lock.json`). Twelve are **not
adopted yet**, pending upstream changes requested in
2AMLogic/sky130-modexp#211. None is rewritten in this repo: an edited copy
would stop matching its stamp and become an unrecorded fork.

## Adopted (3)

The design name `modexp` appears only in comments or docstrings, and the files
take every path as an argument or read stdin, so they behave identically at any
depth.

| Upstream path | Local path |
|---|---|
| `flow/tie_constants.py` | `flow/common/tie_constants.py` |
| `layout/lvs/expand_concat_assigns.py` | `layout/lvs/common/expand_concat_assigns.py` |
| `verification/gate-level/sky130_fd_sc_hd_sim_defines.v` | `verification/gate-level/common/sky130_fd_sc_hd_sim_defines.v` |

## Not adopted (12)

Two reasons, both properties of the upstream files (measured by reading them at
the pin, not by running them).

**A. Functional coupling to the `modexp` design name.** Not PDK-independent as
written.

| Path | Coupling |
|---|---|
| `layout/lvs/build_reference_netlist.py` | pops pin `"modexp"`, writes `.SUBCKT modexp` |
| `verification/gate-level/spice_to_verilog.py` | `DEFAULT_TOP_CELL = "modexp"`, self-test assumes this design |
| `flow/run-par.sh` | default request and outputs named `modexp.*` / `par-modexp.json` |
| `flow/run-corner-sweep.sh` | `modexp_synth_tied.v`, `par-modexp.json`, `"hdl_toplevel": "modexp"` |
| `flow/run-sta-corner-sweep.sh` | `sta-modexp.json`, `layout/modexp.def` |
| `verification/gate-level/run-gate-level-sim.sh` | `test_modexp.py`, `modexp_post_route.v`, `request-modexp-gate-level*.json` |
| `verification/signoff/README.md` | documents that block's own signoff evidence |

**B. Repo root or sibling files found by path depth.** Under `common/` these
resolve the wrong root; the failure is silent, which is worse than a loud one.

| Path | Coupling |
|---|---|
| `verification/_repo_utils.py` | `REPO_ROOT = Path(__file__).parent.parent` |
| `verification/check_records.py` | takes `REPO_ROOT` from `_repo_utils` |
| `verification/check_pins.py` | default `--repo-root` is `parent.parent` |
| `scripts/openroad-smoke-test.sh` | `REPO_ROOT` from `dirname/..`; also needs `scripts/openroad-smoke/` siblings that are not candidates |
| `scripts/openroad-docker.sh` | reads the PDK pin from a sibling `setup-env.sh` with errors discarded; absent under `scripts/common/`, the PDK-revision check is skipped without a message |

(`flow/run-corner-sweep.sh`, `flow/run-sta-corner-sweep.sh` and
`verification/gate-level/run-gate-level-sim.sh` also have reason B.)

## How `verification/signoff/README.md` is followed

It describes upstream's signoff manifest layout for a different block, so it is
not vendored. This repo has no `manifests/` yet; when it does, its structure
follows the upstream README at the pinned commit (read by reference, not
copied) and any departure gets its own decision record.

## Consequences

- This repo has no flow driver, record linter or LVS helper yet. Until
  2AMLogic/sky130-modexp#211 lands and the pin moves, any of those needed here
  comes from that move, not from a local rewrite. Issues #4 (flow smoke) and #7
  (CI) must account for this.
- Revisit when upstream pushes a commit that resolves #211: re-pin, vendor the
  twelve files, and supersede this record.
- No claim about the vendored files running in this repo is made. Nothing is
  wired into CI or executed by this decision.
