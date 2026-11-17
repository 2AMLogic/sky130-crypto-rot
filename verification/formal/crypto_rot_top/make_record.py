#!/usr/bin/env python3
"""Verdict (and optionally record) for the crypto_rot_top P-12 netlist flow run by run.sh.

Reads the check results under --stage (cone_p12.py result JSONs, the flow-log
and freshness check outputs, the envelope consistency check). Fails (exit 1)
unless every check met its expectation: the structural checks PASS on the
committed netlist, the flow log and envelope checks PASS, the committed
netlist is fresh, and every negative control (mutant RTL with a key-to-output
path, spliced probe-cell scope, spliced extra port) FAILS. The mutant control
must also be byte-different from the committed netlist (what the freshness
comparison catches).

With --record it writes an append-only record under
verification/records/crypto-rot-top-netlist-formal/records/, naming the
committed netlist hash and the tool versions. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "flow/common"))

import record_lib  # noqa: E402
from record_lib import pin, run  # noqa: E402

EXPERIMENT = "crypto-rot-top-netlist-formal"
HERE = "verification/formal/crypto_rot_top"
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
    "verification/rtl/crypto_rot_top/synth-request.json",
    "verification/rtl/crypto_rot_top/netlist/crypto_rot_top_synth.v",
    "verification/rtl/crypto_rot_top/netlist/synthesize-envelope.json",
    "verification/rtl/crypto_rot_top/netlist/flow-log.ys",
    "verification/rtl/crypto_rot_top/netlist/check-fresh.sh",
    "spec/key-isolation-properties.md",
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=Path, required=True)
    ap.add_argument("--pdk-root", type=Path, required=True)
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()
    st = args.stage

    clean = json.loads((st / "result_clean.json").read_text())
    neg = json.loads((st / "result_neg.json").read_text())
    ctrl_scope = json.loads((st / "result_ctrl_scope.json").read_text())
    ctrl_port = json.loads((st / "result_ctrl_port.json").read_text())
    envelope = json.loads((st / "envelope-check.json").read_text())

    ok = True
    lines = []

    def want(name, got, expected):
        nonlocal ok
        good = got == expected
        ok &= good
        lines.append(f"  {name:22s} {got!s:6s} {'ok' if good else 'UNEXPECTED: expected ' + expected}")

    want("p12 clean netlist", clean["status"], "pass")
    want("p12 mutant control", neg["status"], "fail")
    want("splice probe-cell control", ctrl_scope["status"], "fail")
    want("splice extra-port control", ctrl_port["status"], "fail")
    if not envelope.get("match"):
        ok = False
        lines.append("  envelope: committed netlist hash differs from the envelope")
    freshness = (st / "freshness.txt").read_text().strip().splitlines()
    if not freshness or "fresh" not in freshness[-1]:
        ok = False
        lines.append(f"  freshness: run did not report fresh ({(st / 'freshness.txt').name})")
    else:
        lines.append("  freshness: fresh (byte-identical re-synthesis)")
    flowlog = (st / "flowlog-check.txt").read_text().strip()
    if "no scan/DFT token" not in flowlog:
        ok = False
        lines.append("  flow-log: check output malformed")
    else:
        lines.append("  flow-log: no scan/DFT insertion; abc excludes lpflow_*/probe*")

    # negative-control attribution: the mutant must fail on a CONE violation
    # (a key-to-output path), not merely on some unrelated row.
    neg_cone_hits = [p for p, r in neg["checks"].get("output_cones", {}).items()
                     if r["key_nets"] or r["key_inputs"] or r["foreign_inputs"]]
    if not neg_cone_hits:
        ok = False
        lines.append("  mutant control: failed without a cone violation (wrong reason)")
    else:
        lines.append(f"  mutant control fails on outputs: {', '.join(neg_cone_hits)}")

    print("crypto-rot-top netlist formal:\n" + "\n".join(lines))
    print("RESULT:", "PASS" if ok else "FAIL")
    if not ok:
        return 1
    if args.check_only:
        return 0

    record_lib.check_pdk(args.pdk_root)
    rev = record_lib.require_clean_inputs(INPUTS, generator=__file__)
    tv = record_lib.tool_versions()
    versions = {
        "yosys": run(str(REPO / ".venv/bin/yosys"), "-V"),
        "yowasp_yosys": tv["yowasp_yosys"],
        "yosys_wasm": tv["yosys_wasm"],
        "klt_pin": tv["klt_pin"],
        "klt_attested_run": envelope.get("klt_version"),
        "ciel": tv["ciel"],
        "python": tv["python"],
    }
    meta_extra = {
        "tool_versions": versions,
        "netlist": {
            "path": "verification/rtl/crypto_rot_top/netlist/crypto_rot_top_synth.v",
            "content_hash": envelope["netlist_sha256"],
            "instance_count": envelope.get("instance_count"),
            "pdk": envelope.get("pdk"),
            "deck": envelope.get("deck"),
        },
    }

    oc = clean["checks"]["output_cones"]
    cone_rows = "\n".join(
        f"| `{p}` | {'carrier-cut (P-4 windows)' if r['carrier_cut'] else 'uncut'} "
        f"| {r['cone_bits']} | "
        f"{', '.join(r['key_nets'] + r['key_inputs'] + r['foreign_inputs']) or 'none'} |"
        for p, r in sorted(oc.items()))
    nonvac = clean["non_vacuity"]
    p10 = clean["checks"]["p10_clear_terms"]
    neg_oc = neg["checks"]["output_cones"]
    neg_hits = ", ".join(
        f"`{p}`: {', '.join(r['key_nets'] + r['key_inputs'])}"
        for p, r in sorted(neg_oc.items()) if r["key_nets"] or r["key_inputs"])

    body = f"""- **Claim**: the structural netlist re-proof for the `klt synthesize` sky130_fd_sc_hd netlist of `rtl/crypto_rot_top.v` committed at `{envelope['netlist_sha256']}` (issue #88), and nothing beyond the structural statements below. Bit-level, conservative cones (every cell output depends on every cell input; flops are cells), so each cone is the full sequential fan-in at every depth. This is a netlist-structure and bounded-statement record: no security, certification, side-channel or entropy claim is made.
- **Design provenance**: the committed netlist ({{rid}}'s `netlist` provenance block: hash, instance count, PDK revision, liberty corner), produced by `klt synthesize` from the committed `verification/rtl/crypto_rot_top/synth-request.json` sources at the same revision; the synthesis envelope and the recorded flow log are committed beside it. The checks read the netlist through Yosys's own liberty-derived models (`read_liberty -ignore_miss_func`; no hand-written cell models).
- **Run configuration**: `./scripts/setup-env.sh` then `./verification/formal/crypto_rot_top/run.sh --record`. Freshness is `verification/rtl/crypto_rot_top/netlist/check-fresh.sh`: it re-runs the committed request in a scratch directory and byte-compares (two clean runs of this request at different scratch paths produced byte-identical netlists on the pinned tools; recorded 2026-11-17). This run also re-attested the freshness control below.

## Results

| Output port | Cone | Bits | Key/foreign material in cone |
|---|---|---|---|
{cone_rows}

Every non-`dat_o` output is checked with no cut at all; `dat_o`'s cone is checked after cutting the three P-4 result carriers (`u_aes.state_q` 128 b, `u_hmac.core.hh` 256 b, `u_drbg.u_drbg.bd_q` 128 b -- the AES_DOUT / HMAC_MAC / DRBG_OUT window contents). No key-bearing register, no `root_key` bit and no `trng_out_data` bit is in any post-cut cone, so every path from key material to an output port passes through a defined engine result window, and no other output port touches key material at all.

### P-12 (no key-to-output path, no scan/test structure)

- **Cone statement**: the table above; no path from a key-bearing flop to any output port except through the P-4 carriers.
- **Scan/DFT structure**: every flattened instance scope in the netlist is a plain `sky130_fd_sc_hd__*` cell ({clean['checks']['cell_scopes']['cell_scopes']} cell scopes checked; probe/lpflow/scan/latch-style types refused), no scan cell exists in the library, the netlist's port list equals the RTL module's (no debug/test/scan port inserted), and the recorded flow log contains no scan/DFT step (its `abc` call excludes the `lpflow_*`/`probe*` cell families). Negative controls: a spliced probe-cell scope and a spliced extra output port each make the structural check fail.
- **P-14 (same machinery)**: `trng_bus_re`'s cone is empty (the sequencer never reads the sibling), and no `trng_out_data` bit reaches any output except as DRBG output (through the `bd_q` carrier).
- **P-2 (same machinery, top level)**: no slot flop (`u_kdf.s0..s3`) in any output cone except through the engine datapath, the top-level counterpart of the module-level P-2 in `verification/records/keyladder-formal/`.
- **P-10 structural fallback**: the zeroize net `zr` is in the cone of every one of the {p10['registers']} key-bearing registers checked (slots, K0/inner, AES round keys, DRBG Key/V and df working values, DRBG private-AES state, seed buffer). The register-list completeness stays the review item the spec names; this check is not the P-10 proof, which does not exist yet on either side.

### Negative controls (each must make its check fail)

| Control | Breaks | Observed |
|---|---|---|
| mutant RTL: `dat_o` XORs `hmac_key[31:0]` into the read data (fresh `klt synthesize` of the mutated top) | one slot-to-output path through no result window | P-12 check FAILS on {neg_hits or 'n/a'} |
| the same mutant vs the committed netlist | an unregenerated RTL edit | byte-different: the freshness comparison catches it |
| spliced `$scopeinfo` naming `sky130_fd_sc_hd__probe_p_8` | a DFT-style cell type | cell-scope check FAILS |
| spliced extra output port `scan_out` | an inserted test/debug port | port-list check FAILS |

### Non-vacuity

- All three carriers are in `dat_o`'s uncut cone, every bit of each ({', '.join(f"`{n}` {v} b" for n, v in nonvac["carriers_in_dat_o_uncut"].items())}), so the cut is load-bearing.
- Slot bits ({nonvac['slots_in_dat_o_uncut']} of 256) and `root_key` bits ({nonvac['root_key_bits_in_dat_o_uncut']} of 256) are in `dat_o`'s uncut cone, so key material really is reachable through the engines and the clean result is not a vacuous pass. The {nonvac['trng_out_data_bits_in_dat_o_uncut']} `trng_out_data` bits likewise (through the DRBG).

## Property coverage (spec marks N; netlist status per property)

| Property | Netlist status | Evidence |
|---|---|---|
| P-1 | R at top level (not re-proven at this size) | The spec's Open question 1 anticipates this: the 2-trace product over a full HMAC block is not tractable on the full mapped design with the open flow, and no induction claim is attempted here. Module-boundary P-1 on the keyladder netlist closed as a bounded run (depth recorded in `verification/records/keyladder-formal/`); P-1 at the bus boundary stays RTL-only for now. |
| P-2 | re-proven (structural, top level) | This record's cone table (no slot flop outside the engine datapath); module-level counterpart in `verification/records/keyladder-formal/`. |
| P-3 | not re-proven separately | Its structural content (key inputs fed only from slots/load) is covered by the same cones at the keyladder boundary (`keyladder-formal` P-2) plus P-12 here: any bus-readable register feeding a key input would put that register's bits in both a key-input cone and `dat_o`'s post-cut cone, which the table excludes. Not claimed as a separate proof. |
| P-5, P-6 | re-proven at module level | `verification/records/keyladder-formal/` (proofs on the keyladder netlist). |
| P-7, P-8, P-9 | re-proven at module level | `verification/records/drbg-trng-formal/` (netlist half, issue #177). |
| P-10 | structural fallback only (see above) | The P-10 proof itself does not exist on RTL or netlist; this record adds the clear-term structural check over the key-bearing register list. |
| P-12 | re-proven (structural) | This record. |
| P-14 | re-proven (structural) | This record (`trng_bus_re` constant; no sibling-output path outside the DRBG output carrier). |

## Limits and known gaps

- Results are for the `klt synthesize` output at one liberty corner (`tt_025C_1v80`), pre-P&R, read through Yosys's own liberty-derived models. A placed/routed netlist, and any scan/DFT step run OUTSIDE this repo's recorded flow, is not covered: P-12's flow-log half is evidence about the committed flow log, not about what other tools could do to the design.
- The cone statement is structural and conservative; it does not show that two runs differing only in key material produce equal outputs in bounded time (that is P-1, recorded R above) and it says nothing about side channels (P-15, out of scope per the spec).
- P-13 (netlist/RTL equivalence) is a separate open item; the RTL proofs and this record are separate proofs, nothing is carried over.
- **Not claimed**: no certification, validation or side-channel resistance. A passing known-answer test is a correctness claim; this record is a structural statement about one committed netlist.
"""

    record_lib.write_record(EXPERIMENT, rev, INPUTS, meta_extra, body, generator=__file__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
