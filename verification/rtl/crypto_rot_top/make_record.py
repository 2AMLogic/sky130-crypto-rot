#!/usr/bin/env python3
"""Verdict (and optionally record) for the crypto_rot_top flow run by run.sh.

Reads flow/build/crypto_rot_top/{sim,synth}.json. Fails (exit 1) unless the
simulation passed and the synthesis status is ok with no latches, combinational
loops or multi-driven nets. With no --check-only it also writes an append-only
record under verification/records/crypto-rot-top-sim/records/. Standard library
only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "flow/common"))

import record_lib  # noqa: E402

NAME = "crypto_rot_top"
EXPERIMENT = "crypto-rot-top-sim"
# The inputs OUTSIDE this directory. The tracked files beside this generator
# are derived by record_lib.own_inputs(), and the shared flow helpers by
# shared_inputs(); neither is listed here (issues #124, #146).
INPUTS = (
    "rtl/sha256/sha256_core.v",
    "rtl/hmac/hmac_sha256.v",
    "rtl/keyladder/keyladder.v",
    "rtl/aes/aes_core.v",
    "rtl/drbg/ctr_drbg.v",
    "rtl/trng_if/trng_if.v",
    "rtl/drbg/drbg_top.v",
    "rtl/crypto_rot_top.v",
    "verification/model/aes.py",
    "verification/model/hmac_sha256.py",
    "verification/model/kdf.py",
    "verification/model/ctr_drbg.py",
    "verification/model/vectorlib.py",
    "verification/vectors/fips197.txt",
    "verification/vectors/rfc4231.txt",
    "verification/rtl/trng_if/trngmodel.py",
)

# Which test covers which ratified spec row (issue #296). Keys are the
# testcases of test_crypto_rot_top.py; values are row ids in
# manifests/spec-rows.json. Validated, not just rendered: a test missing
# from the mapping (a new testcase) or a row id absent from spec-rows.json
# refuses the verdict, and a row no test names is listed under Gaps in the
# record, never omitted. Notes carry the "partial here" honesty: the rows
# whose TB half lives in a per-core bench, or whose FORMAL half is the
# sibling's, say so where they are covered.
TEST_TO_ROWS = {
    "test_status_regs": ("5.1", "5.3", "6.1", "6.2", "6.3"),
    "test_irq_sticky": ("4.5", "5.2", "6.3"),
    "test_kats": ("1.1", "1.2", "1.3", "1.4", "1.5", "2.1", "2.3", "2.4",
                  "2.5", "3.1", "3.2", "3.3", "3.4", "3.5", "5.3"),
    "test_drbg": ("4.1", "4.2", "4.3", "4.6", "6.3"),
    "test_zeroize": ("4.5", "5.2", "5.4", "5.5", "6.3"),
    "test_escalation": ("5.3",),
    "test_key_readback": ("3.6", "6.4"),
}
ROW_NOTES = {
    "1.4": "single-block ECB through the bus (FIPS 197); the SP 800-38A F.1 multi-block vectors are the aes core bench's row",
    "2.1": "through HMAC-SHA-256 only (RFC 4231 + model cross-checks); the direct FIPS 180-4 digests and the million-`a` are the sha256 core bench's row",
    "2.3": "empty, partial-final-word and multi-word messages exercise the hardware padding path; the 55/56/63/64/119 boundary sweep is the sha256 core bench's row",
    "2.4": "RFC 4231 cases 1-3 only (case 4's 131-byte key is not bus-reachable in v1, 0009; cases 6-7 not run here)",
    "2.5": "the TB half only (bus keys enter through the write-only KEY_LOAD window); the never-on-the-bus half is FORMAL P-3/P-5",
    "3.1": "the TB half only (root-key derivations match the model); FORMAL P-1 is the sibling's",
    "3.6": "the TB half only (no read path found); FORMAL P-1/P-2 are the sibling's",
    "4.1": "golden-model cross-check with the derivation function; the published CAVP AES-128 use-df vectors are the drbg core bench's row",
}
GAP_NOTES = {
    "1.6": "the 11-cycle count is measured in the aes core bench; this suite polls DONE and makes no cycle claim",
    "2.2": "the 32-bit byte counter and the boundary-length sweep are the sha256 core bench's row; this suite's messages are at most 24 bytes",
    "2.6": "the 65-cycle count is measured in the sha256 core bench",
    "4.4": "the 2^16 reseed interval is the drbg core bench's row (and FORMAL P-8); this suite checks only the v1 GEN_BITS <= 128 cap (0009), narrower than the row's 1024 bits",
    "4.7": "a wording constraint, not a testable row: the spec names no verification method, and the Claim above uses the sanctioned seeding wording",
    "7.1": "STA, #50; every section 7 row is target, unmeasured",
    "7.2": "TB half in the aes core bench; STA half in #50",
    "7.3": "TB half in the sha256 core bench; STA half in #50",
    "7.4": "the tt_025C_1v80 cell-area figure is recorded under Result (SYNTH, not a test); the P&R utilization half is unmeasured",
    "7.5": "DRC + LVS: no committed result yet",
}


def fv_extra_check(out_dir):
    """The record's gate on the committed functional-verification report.

    Two things refuse the verdict (and so every record): fv_report.py's
    freshness verdict on the committed pair -- input hashes, report hash,
    and that the committed report's verdict equals this run's -- and the
    coverage-table validation below, so the mapping cannot drift from the
    bench or from manifests/spec-rows.json.
    """
    import fv_report

    ok, text, data = fv_report.verify_run(out_dir)
    sim = json.loads((Path(out_dir) / "sim.json").read_text())
    spec = json.loads((REPO / "manifests/spec-rows.json").read_text())
    rows = {r["id"]: r["item"] for r in spec["rows"]}
    problems = []
    if spec.get("status") != "ratified":
        problems.append(f"spec-rows.json status {spec.get('status')!r}, not 'ratified'")
    tests = [t["name"] for t in sim.get("tests", [])]
    unmapped = sorted(set(tests) - set(TEST_TO_ROWS))
    gone = sorted(set(TEST_TO_ROWS) - set(tests))
    if unmapped:
        problems.append(f"test(s) {unmapped} in sim.json are absent from TEST_TO_ROWS")
    if gone:
        problems.append(f"TEST_TO_ROWS names test(s) {gone} the bench did not run")
    covered = {row for rows_ in TEST_TO_ROWS.values() for row in rows_}
    unknown = sorted((covered | set(GAP_NOTES) | set(ROW_NOTES)) - set(rows))
    if unknown:
        problems.append(f"row id(s) {unknown} are not in spec-rows.json")
    stray_gap = sorted(set(GAP_NOTES) & covered)
    if stray_gap:
        problems.append(f"GAP_NOTES names covered row(s) {stray_gap}")
    stray_note = sorted(set(ROW_NOTES) - covered)
    if stray_note:
        problems.append(f"ROW_NOTES names gap row(s) {stray_note}")
    if problems:
        return False, text + "; coverage: " + "; ".join(problems), data

    lines = ["| Row | Item | Covered by |",
             "|---|---|---|"]
    for rid in sorted(rows, key=lambda r: tuple(int(x) for x in r.split("."))):
        if rid in covered:
            names = ", ".join(t for t in tests if rid in TEST_TO_ROWS[t])
            cell = names + (f" ({ROW_NOTES[rid]})" if rid in ROW_NOTES else "")
            lines.append(f"| {rid} | {rows[rid]} | {cell} |")
    gaps = sorted(set(rows) - covered,
                  key=lambda r: tuple(int(x) for x in r.split(".")))
    for rid in gaps:
        note = GAP_NOTES.get(rid, "no test in this suite")
        lines.append(f"| {rid} | {rows[rid]} | GAP: {note} |")
    data = {**data, "spec_status": spec["status"], "row_count": len(rows),
            "gap_count": len(gaps), "coverage_table": "\n".join(lines)}
    return ok, text, data


def body(ctx) -> str:
    sim, syn = ctx.sim, ctx.syn
    args = ctx.args
    return f"""- **Claim**: `rtl/crypto_rot_top.v` -- the top level integrating `rtl/aes/aes_core.v`, `rtl/hmac/hmac_sha256.v`, `rtl/keyladder/keyladder.v` and `rtl/drbg/drbg_top.v` (which embeds `trng_if`) behind the ratified register bus (0005) and register map (0009) -- runs the published AES and HMAC known-answer vectors end to end through the bus with slot keys (FIPS 197 both directions with the vector key loaded into a slot; RFC 4231 cases 1-3 with the case key loaded; case 4's 131-byte key is not bus-reachable in v1 and case 5 is truncated output, both out of scope by 0009), derives slot keys that match `verification/model/kdf.py` and produces DRBG output that matches `verification/model/ctr_drbg.py` seeded from the sibling stub's words; refuses every access class 0009 makes a violation (undefined address, write to a read-only register, write while the addressed engine is busy, read of a write-only location) with `err_o`, a zero read value, the `FAULT_CLS` bit and the ERROR pending bit; escalates (zeroize + `FAULT_ZEROIZED`) on a second violation within one operation and on any violation during key load; and performs every `target-spec.md` section 5 zeroize event (software `ZEROIZE`, synchronized TRNG alarm through `ALARM_ZEROIZED` and its recovery at the source, TRNG `gated` to `RESEED_REQUIRED` with keys kept, reset, and zeroize during an in-flight AES operation). The lifecycle FSM (`STATUS.STATE`), `ZCAUSE`, `FAULT_CLS`, sticky `IRQ_PEND` with the single mask and level `irq_o`, the DENY paths (a denied start runs no block) and the GEN_BITS > 128 refusal (ERR=3 without starting) are all checked. A correctness claim for this block's simulated behaviour only; it is not a key-isolation proof (the FORMAL sibling is #46's second child) and makes no side-channel, timing, entropy or certification claim (0008).
- **Design provenance**: RTL, pre-synthesis simulation (Icarus); the synthesis figure is the `klt synthesize` output for the same sources. No gate-level simulation was run.
- **Run configuration**: `./scripts/setup-env.sh` then `./verification/rtl/crypto_rot_top/run.sh --record`. Simulation: `klt functional-verification verification/rtl/crypto_rot_top/sim-request.json` (engine icarus, `random_seed` 1). Synthesis: `klt synthesize verification/rtl/crypto_rot_top/synth-request.json --pdk sky130A --pdk-root {args.pdk_root}`, liberty corner `tt_025C_1v80`, single corner, pre-P&R, cell area only, no clock target. No STA was run.
- **Statistical convention**: deterministic; zero-mismatch pass/fail. The bench drives the bus only (no hierarchical DUT access); the sibling pins come from the port-protocol stub `verification/rtl/trng_if/trngmodel.py` (40:1 clock ratio), as for the `drbg_top` bench. Golden values: the committed, provenance-checked FIPS 197 and RFC 4231 vector files for the published KATs; `verification/model/` for the derived-key AES/HMAC cross-checks and the DRBG (whose seed words are the stub's, so the model is seeded with exactly what the block saw). Key-adjacent readback is a directed sweep of all 128 word addresses against the set of 32-bit words of the root key, every slot key (derived and loaded), the seed words and the DRBG `Key`/`V` from the model. Negative controls: `./verification/rtl/crypto_rot_top/run.sh --negative-control` builds four variants and the bench fails on each: `TOP_NEG_ZEROIZE` (the zeroize level no longer reaches the key ladder), `TOP_NEG_FAULT` (an undefined-address access no longer records `FAULT_CLS` bit 0), `KL_NEG_ZEROIZE` (the ladder's own control: slot 3 omitted from zeroize) and `TOP_NEG_IRQ_STICKY` (a register write on an event cycle swallows the event again: `IRQ_PEND`/`ZCAUSE` lose set dominance and the directed `test_irq_sticky` fails).
- **Result**: PASS. Simulation: {sim['passed_count']}/{sim['test_count']} tests passed ({ctx.summary}). Synthesis: status `{syn['status']}`, {syn['instance_count']} instances, {syn['area_um2']} um2 ({syn['sequential_area_um2']} um2 sequential, includes the AES, HMAC/SHA-256 and DRBG engines), no latches, combinational loops or multi-driven nets. Timing is `null`: no timing claim; the section 7 targets remain target, unmeasured. Not checked here: the committed netlist, the freshness check, the P-12 netlist re-proof and `klt signoff --attest 1` (sibling issue under #46); floorplan, P&R, GDS, LVS, STA (#47, #49, #50); and the formal properties P-1/P-2/P-11/P-12, which are stated against this bus front end but proved by the FORMAL sibling.
- **Functional-verification report**: this run's `klt functional-verification` JSON is committed at `{ctx.extra['report']}` ({ctx.extra['report_sha256']}), reproducible from the committed request with `./verification/rtl/crypto_rot_top/run.sh` (the cold-start suite runs the same step); the {ctx.extra['inputs']} input hashes in its envelope (`functional-verification-envelope.json`: the request, every source it names, `tb_top.v`, the bench module and the bench's golden models/vectors -- the pinned klt 0.8.0 writes no input hashes and has no `--check`, so the freshness check is this repo's own, `python3 verification/rtl/crypto_rot_top/fv_report.py check`, exit 3 on drift, CI's `fv-report-freshness` job) name what the verdict was produced against, and the three absolute artifact paths klt 0.8.0 echoes into `environment` are rewritten repo-relative when committed (2AMLogic/klayout-tools#5784; a pin bump retires the rewrite). This is the functional half of T1 item 5's evidence only: the item is not claimed `met` here -- the multi-corner `klt sta` half remains #50's, after #47 -- and a KAT pass is a correctness claim, never a security claim (0008).
- **Spec-row coverage** (from `manifests/spec-rows.json`, status `{ctx.extra['spec_status']}`, {ctx.extra['row_count']} rows; every test of this suite is mapped, every row is either mapped or listed as a gap with its note):

{ctx.extra['coverage_table']}
{ctx.klt_provenance}
- **Links**: `rtl/crypto_rot_top.v`, `verification/rtl/crypto_rot_top/`, `spec/target-spec.md` sections 5-6, `spec/decision-records/0005-register-bus.md`, `spec/decision-records/0009-register-map.md`, issue #87 (parent #46).
"""


def main() -> int:
    return record_lib.main(name=NAME, experiment=EXPERIMENT, inputs=INPUTS,
                           generator=__file__, extra_check=fv_extra_check,
                           author="Loom builder agent (issue #296)", body=body)


if __name__ == "__main__":
    sys.exit(main())
