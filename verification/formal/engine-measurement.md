# Engine measurement: trace generation and solver coverage, P-7/P-8/P-9 RTL tasks

Measurement for #309 (operator split of #129 items 3-4). Nothing here changes a
committed engine, `aigsmt`, depth, property or `expect` line; the committed
`.sby` files are untouched and no record under `verification/records/` is
written. The driver that produced every row is committed beside this report
(`verification/formal/measure_engines.sh`); its variant copies live under
`flow/build/` and differ from the committed files only in the lines named
below.

## Commit and tools

Measured on `2145d4a` ("Merge pull request #310", 2026-11-23), branch
`feature/issue-309`, by `./verification/formal/measure_engines.sh` on the
dispatch host `loom-worker` (sequential runs, one sby at a time).

| Tool | Identity |
| --- | --- |
| sby / yosys / yosys-smtbmc / yosys-witness | YoWASP wheel `yowasp-yosys==0.68.0.0.post1208`, `yosys.wasm` sha256 `e37a7e65e3fa4efbbd64a9c1b0e906be16cdc6c4d5273109d17537f78449f38c` (matches the pin in `scripts/setup-env.sh`); `sby --version` reports "unknown SBY version", so the wasm digest is the identity |
| z3 | `z3-solver==5.3.2.0`, binary sha256 `c45e787b5d1a3d94079d1e83b98e23bbc884ccaf542ea38c3814f31ac2f79197` (matches the pin), reports "Z3 version 5.3.2 - 64 bit" |
| host yosys-abc | `/home/ubuntu/.local/bin/yosys-abc`, "UC Berkeley, ABC 1.01 (compiled Nov 22 2026 07:08:23)", sha256 `e19cd99593cd94b69b30502fb541b2d1071178c565f482193518f5ab3b9599b9` — **unpinned**: sby's `abc` engines exec whatever `yosys-abc` is on `$PATH` (CI: the apt `yosys` package) |

## Method

Three passes over the ten RTL tasks of `p7_p8.sby` + `p9.sby`:

- **base** — the committed `.sby` files exactly as `run.sh` runs them
  (`abc pdr` for the two unbounded proofs, `abc bmc3` for the eight bounded
  tasks, `aigsmt none`). A fresh same-machine, same-commit baseline; it
  reproduces the 2026-11-15 record (`verification/records/drbg-trng-formal/
  records/20261115-084328-a801ec1.md`) row for row.
- **aig** (trace conversion) — copies with the single change
  `aigsmt none` -> `aigsmt z3`. Engines, depths, properties untouched.
- **smt** (solver coverage) — copies with every engine line changed to
  `smtbmc z3` and a **600 s per-task timeout** added; modes and depths
  untouched. For the two `prove` tasks sby runs k-induction (base case +
  induction as two solver processes).

sby resolves `[files]` against its working directory, so the copies re-point
the source paths at the committed tree; `diff` of each copy against the
original shows only the `aigsmt`/engine/`timeout` lines and those paths.
Elapsed seconds are sby's own "Elapsed clock time" per task. Exit code is
sby's (`expect fail` tasks that FAIL exit 0).

## Results

Trace = non-empty VCD under the task's `engine_0/`. PASS tasks produce no
counterexample by definition (trace "n/a"); base FAIL tasks produce none
because `aigsmt none` skips conversion. The `smt` prove rows' trace is sby's
`trace_induct.vcd`, an induction-step artifact, **not** a reachable
counterexample — flagged per row below.

| Pass | File | Task | Engine | Mode | Depth | Status | Exit | Elapsed s | Frame | Trace |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| base | p7_p8.sby | prove | abc pdr | prove | – | PASS | 0 | 2 | – | n/a |
| base | p7_p8.sby | reach_valid | abc bmc3 | bmc | 90 | FAIL (expected) | 0 | 2 | 54 | no (aigsmt none) |
| base | p7_p8.sby | reach_over | abc bmc3 | bmc | 160 | FAIL (expected) | 0 | 2 | 60 | no (aigsmt none) |
| base | p7_p8.sby | neg_interval | abc bmc3 | bmc | 200 | FAIL (expected) | 0 | 2 | 61 | no (aigsmt none) |
| base | p7_p8.sby | neg_seeded | abc bmc3 | bmc | 40 | FAIL (expected) | 0 | 1 | 2 | no (aigsmt none) |
| base | p9.sby | bmc | abc bmc3 | bmc | 30 | PASS | 0 | 6 | – | n/a |
| base | p9.sby | prove | abc pdr | prove | – | PASS | 0 | 12 | – | n/a |
| base | p9.sby | neg_bound | abc bmc3 | bmc | 30 | FAIL (expected) | 0 | 11 | 5 | no (aigsmt none) |
| base | p9.sby | reach_nonzero | abc bmc3 | bmc | 30 | FAIL (expected) | 0 | 7 | 5 | no (aigsmt none) |
| base | p9.sby | neg_zeroize | abc bmc3 | bmc | 30 | FAIL (expected) | 0 | 7 | 2 | no (aigsmt none) |
| aig | p7_p8.sby | prove | abc pdr | prove | – | PASS | 0 | 2 | – | n/a |
| aig | p7_p8.sby | reach_valid | abc bmc3 + aigsmt z3 | bmc | 90 | FAIL (expected) | 0 | 19 | 54 | **yes** |
| aig | p7_p8.sby | reach_over | abc bmc3 + aigsmt z3 | bmc | 160 | FAIL (expected) | 0 | 21 | 60 | **yes** |
| aig | p7_p8.sby | neg_interval | abc bmc3 + aigsmt z3 | bmc | 200 | FAIL (expected) | 0 | 27 | 61 | **yes** |
| aig | p7_p8.sby | neg_seeded | abc bmc3 + aigsmt z3 | bmc | 40 | FAIL (expected) | 0 | 2 | 2 | **yes** |
| aig | p9.sby | bmc | abc bmc3 + aigsmt z3 | bmc | 30 | PASS | 0 | 6 | – | n/a |
| aig | p9.sby | prove | abc pdr + aigsmt z3 | prove | – | PASS | 0 | 11 | – | n/a |
| aig | p9.sby | neg_bound | abc bmc3 + aigsmt z3 | bmc | 30 | FAIL (expected) | 0 | 7 | 5 | **yes** |
| aig | p9.sby | reach_nonzero | abc bmc3 + aigsmt z3 | bmc | 30 | FAIL (expected) | 0 | 7 | 5 | **yes** |
| aig | p9.sby | neg_zeroize | abc bmc3 + aigsmt z3 | bmc | 30 | FAIL (expected) | 0 | 6 | 2 | **yes** |
| smt | p7_p8.sby | prove | smtbmc z3 | prove (k-induction) | – | **UNKNOWN** (does not close) | 4 | 43 | – | induction cex only |
| smt | p7_p8.sby | reach_valid | smtbmc z3 | bmc | 90 | **TIMEOUT** at 600 s cap | 8 | 601 | – | no |
| smt | p7_p8.sby | reach_over | smtbmc z3 | bmc | 160 | **TIMEOUT** at 600 s cap | 8 | 601 | – | no |
| smt | p7_p8.sby | neg_interval | smtbmc z3 | bmc | 200 | **TIMEOUT** at 600 s cap | 8 | 601 | – | no |
| smt | p7_p8.sby | neg_seeded | smtbmc z3 | bmc | 40 | FAIL (expected) | 0 | 2 | 2 | **yes** |
| smt | p9.sby | bmc | smtbmc z3 | bmc | 30 | PASS | 0 | 184 | – | n/a |
| smt | p9.sby | prove | smtbmc z3 | prove (k-induction) | – | **UNKNOWN** (does not close) | 4 | 84 | – | induction cex only |
| smt | p9.sby | neg_bound | smtbmc z3 | bmc | 30 | FAIL (expected) | 0 | 3 | 5 | **yes** |
| smt | p9.sby | reach_nonzero | smtbmc z3 | bmc | 30 | FAIL (expected) | 0 | 3 | 5 | **yes** |
| smt | p9.sby | neg_zeroize | smtbmc z3 | bmc | 30 | FAIL (expected) | 0 | 2 | 2 | **yes** |

Pass totals (sby elapsed, ten tasks): base 52 s, aig 108 s, smt 2124 s.

TIMEOUT rows carry no sby engine summary line (the task was killed at the
cap), hence "none" in the raw `results.tsv` engine column; the engine is
`smtbmc z3` by construction of the copy.

### Trace availability (measurement A)

All seven expected-FAIL tasks produced a non-empty
`engine_0/trace{.vcd,.yw,.aiw,.smtc,_tb.v}` under `aigsmt z3`, at the same
failing frame as the base run (54/60/61/2 and 5/5/2). The two PASS proofs are
unaffected (no solver call happens without a counterexample).

**Spot-check (named task: `aig_p7_p8_reach_valid`)**: the witness converted
and the violated signal is the asserted one. The property is
`if (!f_init) assert (!blk_valid)` (`fv_drbg.v:67`); parsing
`aig_p7_p8_reach_valid/engine_0/trace.vcd` shows a well-formed VCD declaring
`blk_valid` (id `n6`) whose final value is `1` — the asserted condition is
violated in the trace's last step — with the final `smt_step` tick 55,
matching the logged "asserted in frame 54" (0-based). Secondary confirmation:
`aig_p7_p8_reach_over`'s trace ends with `reseed_required = 1`, violating
`assert (!reseed_required)` (`fv_drbg.v:70`).

### Unbounded proofs under `smtbmc z3` (measurement B)

Time cap: 600 s per task (the `timeout 600` line added to the smt copies).

- `p7_p8 prove`: **does not close** — not a timeout. Base case PASS; temporal
  induction **fails** at 41 s with an induction counterexample hitting the
  P-7/P-8 asserts at `ctr_drbg.v:352.25-352.83` and `ctr_drbg.v:356.51-356.96`
  (`engine_0/trace_induct.vcd`). sby reports UNKNOWN, exit 4.
- `p9 prove`: **does not close** — same shape. Base case PASS; induction
  fails at 82 s. UNKNOWN, exit 4.

This is the expected legitimate outcome: k-induction without a strengthening
invariant (here: the `ctr_q <= interval + 1` bound that the record text says
`abc pdr` discharges by PDR) cannot close these proofs. Closing them under
smtbmc would require adding invariants — an engine-plus-properties change,
out of scope for a measurement.

## Recommendation

**Engines to retain per task class:**

- Unbounded proofs (`p7_p8 prove`, `p9 prove`, and their netlist
  counterparts): keep `abc pdr`. It closes both RTL proofs in 2-12 s; the
  pinned-toolchain alternative does not close them at all without new
  invariants.
- Bounded checks and negative controls: keep `abc bmc3`. It finishes every
  bounded task in 1-11 s; `smtbmc z3` misses the retention bar outright —
  three of seven expected-FAIL tasks (`reach_valid`, `reach_over`,
  `neg_interval`, i.e. the deep ones: depths 90-200, failing frames 54-61)
  hit the 600 s cap without producing their FAIL, so it does **not** keep
  every expected-FAIL task FAILing. Only the p9-family bounded tasks
  (depth 30) meet their expectations under z3, at 184 s vs 6 s for the one
  PASS row — correct but ~30x slower, with no capability gained (abc already
  yields traces once `aigsmt` is not `none`).
- `smtbmc z3` remains in use where it already works: the keyladder harness
  (`verification/formal/keyladder/*.sby`) is unmeasured here and untouched.

**Trace conversion (`aigsmt z3`):** flipping the single `aigsmt none` line to
`aigsmt z3` preserves every task's verdict, failing frame and exit code, and
yields a waveform for all seven expected-FAIL tasks at a total cost of +56 s
across the ten RTL tasks (52 s -> 108 s). If counterexample waveforms are
wanted from future harness runs (they are the natural artifact for debugging
a negative control), this is a sound change — file it as a separate issue
from this measurement; do not treat this report as having changed it. It
also makes the harness depend on the pinned z3 for the FAIL rows, i.e. one
more thing CI must have — which it already installs for the keyladder tasks.

**Can host `yosys-abc` be dropped?** No, not on this evidence. Callers of the
standalone binary (re-grepped on `2145d4a`; comment-only mentions excluded):

1. `verification/formal/run.sh` — the preflight `command -v yosys-abc` and
   the ten RTL tasks (`p7_p8.sby`, `p9.sby`: `abc pdr`/`abc bmc3`).
2. `verification/formal/net_p7_p8.sby` / `net_p9.sby` — the ten netlist
   re-proof tasks, same abc engines, run by `run.sh --netlist`; **not
   measured under `smtbmc` in this issue**, so no evidence exists that they
   could leave abc (and the netlist proofs closing under PDR says nothing
   about k-induction on the liberty-mapped model).
3. `.github/workflows/ci.yml` (yosys install at lines 104-107) — exists to
   provide `yosys-abc` for the sby abc engines.
4. `verification/formal/measure_engines.sh` (this issue's driver; base and
   aig passes).

Not callers: `verification/formal/crypto_rot_top/run.sh`,
`verification/rtl/crypto_rot_top/netlist/check-fresh.sh` and
`scripts/cold-start-benches.sh` mention yosys-abc only in the
klayout-tools#5780 readline-deadlock comment — their abc activity is the
mapping pass *inside* the pinned wasm yosys (`klt synthesize`), whose
identity is the wasm sha256, not the host binary. Since (1) and (2) keep abc
engines per the recommendation above, host `yosys-abc` stays, and the CI apt
`yosys` step stays with it.

**Recording the ABC binary identity:** recommended. Every `abc pdr`/`abc
bmc3` verdict in this harness rests on an **unpinned** binary that varies
with the host (this run: apt-built ABC 1.01, sha256 `e19cd995…`) — the exact
identity gap the wasm pin exists to close for yosys proper, open for abc.
One extra line in `make_record.py`'s run-configuration text — the resolved
`yosys-abc` path, the version banner it prints, and the binary sha256 —
would make each future record name the engine binary that produced it.
Evaluate-and-implement as a separate issue (this measurement changes no
recording path).

## Reproducing

```
./scripts/setup-env.sh          # pinned venv: sby, yosys(-wasm), z3, witnesses
./verification/formal/measure_engines.sh
```

Writes `flow/build/formal/engine-measurement/results.tsv` (the table's raw
source: pass, file, task, status, exit, engine summary, frame, elapsed,
trace path) and one sby task directory per row. To re-run a single row by
hand, regenerate the copies (the driver's generation block) and run, e.g.
for the spot-checked row:

```
cd flow/build/formal/engine-measurement
../../../../.venv/bin/sby -f -d aig_p7_p8_reach_valid p7_p8.aig.sby reach_valid
```

Status, exit code and frame match the table; elapsed may differ. A task
hitting the cap is TIMEOUT by construction (the smt copies' `timeout 600`),
never PASS/FAIL; a missing z3 or yosys-witness surfaces as a tool-failure
row (non-numeric status), not a solver result.

## Out of scope (unchanged)

Committed engines, `aigsmt`, depths, properties, `expect` lines, the
`make_record.py` EXPECT table, `verification/records/`, the netlist tasks
(callers enumerated only), and the keyladder harness.
