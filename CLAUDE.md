# sky130-crypto-rot — agent instructions

Open-source canary block: a cryptographic root of trust (AES, SHA-256/HMAC,
key ladder, CTR_DRBG) on SkyWater sky130, designed and verified by AI
agents. **Digital.**

- **PDK**: SkyWater sky130 (open PDK, google/skywater-pdk), `sky130_fd_sc_hd`
  standard cells. Digital: cocotb + Icarus, Yosys, OpenROAD; formal property
  checks through the open Yosys-based formal flow (SymbiYosys). Layout, DRC,
  and LVS through klayout-tools (`klt`).
- **Key isolation is the point, and the risk.** The algorithms are checkable
  against published known-answer vectors; the root-of-trust properties are
  not. "No bus access returns key material", "a TRNG alarm zeroizes every
  key slot", "the DRBG never emits output before it is seeded" are
  properties of every path, so they are stated as formal properties and
  re-proven on the synthesized netlist, not only on RTL. A synthesis or
  scan/test insertion step that opens a path to a key is a defect in this
  block, whatever the functional tests say.
- **Scope discipline.** The entropy source is `sky130-trng`'s (this repo's
  `consumes:` edge). Do not design a TRNG, health tests or a conditioner
  here. Take its RTL by a pinned commit in `reuse.lock.json` (see
  `2am/REUSE.md`), specify this side of the interface — the clock-domain
  crossing from its 50 kHz sample clock, its `out_data`/`out_valid`/
  `out_ready` stream, and how `alarm`, `gated` and `startup_done` gate
  seeding — and stop. A defect or missing requirement found in the TRNG is
  filed on `2AMLogic/sky130-trng`, not worked around here. Public-key
  arithmetic is `sky130-modexp`'s; if it is ever added, adopt it or write
  the decision record saying why not.
- **No security claims beyond the evidence.** Do not claim certification,
  validation, or side-channel resistance. A passing known-answer test is a
  correctness claim. TRNG entropy remains provisional until silicon, so
  DRBG seeding claims say "seeded from the sibling's conditioned output at
  its stated operating point", never "full entropy".
- **Friction protocol (the canary's job)**: every time klayout-tools is
  awkward, missing a capability, or wrong for what you need, file an issue at
  `2AMLogic/klayout-tools` describing the tool gap generically — that tracker
  is scoped to the tool, so keep design-specific detail out of it and describe
  the gap, not the design.
- **Verification is the product**: no claim without a testbench. Every
  algorithm core passes the published vectors; every timing claim names its
  liberty corner; recorded results are append-only evidence.
- Spec changes go through `spec/` with a decision record; agents do not relax
  the ratified spec to make results pass.
- **AES-128 at 50 MHz is the target.** Encrypt-only is the fallback and
  AES-256 a stretch. Do not let stretch features drive architecture before
  the target closes.

<!-- BEGIN LOOM ORCHESTRATION -->
This repository uses [Loom](https://github.com/rjwalters/loom) for AI-powered development orchestration — see the Loom repository for the full guide (roles, labels, worktrees, configuration). When installed, Loom also writes a locally-substituted copy of that guide to `.loom/CLAUDE.md`.

Work is coordinated through `loom:` labels on issues and pull requests, and the same roles run either under `loom-daemon` or by hand in an attended session — daemon mode is optional. Create the labels once with `.loom/scripts/sync-labels.sh` (an install ships `.github/labels.yml` but does not create the labels on the forge). A pull request ready for review carries `loom:review-requested`; Judge reviews it and applies `loom:pr` (approved) or `loom:changes-requested`; Doctor fixes a `loom:changes-requested` pull request and returns it to `loom:review-requested`. Only a `loom:pr` pull request gets merged, and always via this repo's merge script (`.loom/scripts/merge-pr.sh`) — never a raw forge merge command such as `gh pr merge`. Full state machine: `.loom/docs/label-state-machine.md`.
<!-- END LOOM ORCHESTRATION -->
