#!/usr/bin/env python3
"""Through-CTS record for the crypto_rot_top place-and-route flow run by
`flow/pnr/crypto_rot_top/run.sh --through-cts --record` (issue #295, the
pre-route half of #47).

Reads `flow/build/pnr/crypto_rot_top/{freshness.txt,pnr.json}` -- the
run.sh artifacts: the check-fresh.sh verdict line and the stage-bounded
(`target_stage: "cts"`) `klt place-and-route` response -- plus the CTS DEF
the response's `unrouted_def_path` names (the placed-instance count is read
from that DEF's own COMPONENTS section, not hand-copied) and the committed
netlist the run placed. Fails (exit 1) unless the freshness check passed,
the flow reached exactly the "cts" stage, the audited DEF's power delivery
is complete, and every hash binding holds: a missing metric or failed stage
leaves no new success record. Like `flow/common/make_timing_record.py` and
`verification/formal/make_record.py`, this drives record_lib's lower-level
helpers directly (check_pdk, require_clean_inputs, tool_versions,
write_record) -- record_lib.main() is the sim+synth entry point and reads
sim.json/synth.json, none of which a place-and-route run produces. Standard
library only.

No routed-GDS claim is made or minted here: the detailed route, the routed
artifacts' record and the item-2 envelope are #47's (run.sh's bare --record
stages the routed artifacts for it; this generator never touches
manifests/). The spec section 7 timing rows stay "target, unmeasured" until
STA (#50) -- any slack figure the response carries is a pre-route estimate,
recorded as data and never graded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "flow/common"))

import record_lib as rc  # noqa: E402

EXPERIMENT = "crypto-rot-top-pnr"
OUT_DIR = REPO / "flow/build/pnr/crypto_rot_top"
NETLIST = "verification/rtl/crypto_rot_top/netlist/crypto_rot_top_synth.v"
NETLIST_ENVELOPE = "verification/rtl/crypto_rot_top/netlist/synthesize-envelope.json"
CHECK_FRESH = "verification/rtl/crypto_rot_top/netlist/check-fresh.sh"
REQUEST = "layout/place-and-route.json"
SPEC = "spec/target-spec.md"

# The inputs OUTSIDE this directory. The tracked files beside this generator
# (run.sh, this file, the flow README) are derived by record_lib.own_inputs(),
# and the shared flow helpers by shared_inputs(); neither is listed here
# (issues #124, #146). The spec is listed: _spec_row() reads the section 7
# area row out of it, so a record must hash and dirty-check the text it
# compares against.
INPUTS = (
    REQUEST,
    NETLIST,
    NETLIST_ENVELOPE,
    CHECK_FRESH,
    SPEC,
)


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def count_def_components(path: Path) -> int:
    """Entries of the DEF's COMPONENTS section: the placed-instance count.

    Each component is one record beginning with `- ` inside the section
    (LEF/DEF rev 5.8 grammar), the same thing OpenROAD's `get_cells`-style
    query would count -- klt 0.8.0 does not thread a placed-instance number
    through its response (its own module docstring says so), so the DEF the
    response itself points at is the honest source.
    """
    count, inside = 0, False
    for line in path.read_text().splitlines():
        if line.startswith("COMPONENTS "):
            inside = True
            continue
        if line.startswith("END COMPONENTS"):
            break
        if inside and line.lstrip().startswith("-"):
            count += 1
    if not inside:
        raise SystemExit(f"pnr: {path} has no COMPONENTS section to count")
    return count


def _load_run() -> tuple[dict, str]:
    """(cts response, freshness line), refusing unless the run is complete."""
    for rel in ("freshness.txt", "pnr.json"):
        if not (OUT_DIR / rel).exists():
            print(f"pnr: not recording, {OUT_DIR / rel} is missing -- run "
                  "flow/pnr/crypto_rot_top/run.sh --through-cts --record first",
                  file=sys.stderr)
            raise SystemExit(1)
    pnr = json.loads((OUT_DIR / "pnr.json").read_text())
    if pnr.get("status") != "ok" or pnr.get("stage_reached") != "cts":
        print(f"pnr: not recording, the flow did not complete through cts "
              f"(status {pnr.get('status')!r}, stage_reached "
              f"{pnr.get('stage_reached')!r})", file=sys.stderr)
        raise SystemExit(1)
    placed = pnr.get("power", {}).get("placed", {})
    if placed.get("status") != "complete":
        print("pnr: not recording, the audited DEF's power delivery is "
              f"{placed.get('status')!r} (missing: {placed.get('missing')})",
              file=sys.stderr)
        raise SystemExit(1)
    freshness = (OUT_DIR / "freshness.txt").read_text().strip().splitlines()
    line = freshness[-1] if freshness else ""
    if "fresh" not in line:
        print(f"pnr: not recording, the freshness guard did not pass this run "
              f"({line!r})", file=sys.stderr)
        raise SystemExit(1)
    return pnr, line


def _netlist_meta(pnr: dict) -> dict:
    """The committed netlist's meta, after refusing unless the flow placed
    exactly it: the response's pinned input hash must equal the committed
    netlist's bytes AND its committed envelope's pin."""
    net_hash = sha256_file(REPO / NETLIST)
    pinned = json.loads((REPO / NETLIST_ENVELOPE).read_text()).get(
        "netlist_sha256", "")
    if pinned.removeprefix("sha256:") != net_hash.removeprefix("sha256:"):
        print(f"pnr: not recording, the committed netlist hash {net_hash} "
              f"differs from synthesize-envelope.json's pin ({pinned})",
              file=sys.stderr)
        raise SystemExit(1)
    placed = pnr.get("provenance", {}).get("input", {}).get("content_hash")
    if placed != net_hash:
        print(f"pnr: not recording, the flow placed a different netlist "
              f"({placed}) than the committed one ({net_hash})",
              file=sys.stderr)
        raise SystemExit(1)
    return {"path": NETLIST, "content_hash": net_hash}


def _cts_def(pnr: dict) -> Path:
    """The CTS DEF the response's `unrouted_def_path` names, or refusal."""
    env = pnr.get("unrouted_def_path")
    if not (isinstance(env, dict) and env.get("scope") == "repo"
            and env.get("path")):
        print(f"pnr: not recording, the response has no repo-scoped "
              f"unrouted_def_path: {env!r}", file=sys.stderr)
        raise SystemExit(1)
    path = REPO / env["path"]
    if not path.is_file():
        print(f"pnr: not recording, the CTS DEF {env['path']} is missing",
              file=sys.stderr)
        raise SystemExit(1)
    return path


def _spec_row() -> str:
    """The section 7 area-budget row, read from the spec rather than restated."""
    text = (REPO / SPEC).read_text()
    m = re.search(r"^\| Area budget \|.*$", text, re.M)
    return m.group(0) if m else "(area budget row not found)"


def _timing_note(pnr: dict, clock_ns: float) -> str:
    """The response's timing fields, labelled as what they are.

    Pre-route estimates at best (placement/CTS-stage parasitic estimation,
    never STA), and possibly absent entirely -- either way the spec section 7
    timing rows stay "target, unmeasured" until #50.
    """
    slack = pnr.get("worst_slack_ns")
    if slack is None:
        return ("worst setup slack not measured at this stage (the response "
                "carries no estimate; STA is #50)")
    return (f"worst setup slack {slack} ns at the {clock_ns} ns "
            "target -- a PRE-ROUTE ESTIMATE recorded as data, not a timing "
            "claim; the section 7 timing rows stay \"target, unmeasured\" "
            "until STA (#50)")


def record_body(ctx) -> str:
    pnr, netlist, cts_def = ctx.pnr, ctx.netlist, ctx.cts_def
    placed = pnr["power"]["placed"]
    core_mm2 = pnr["core_area_um2"] / 1.0e6
    die_mm2 = pnr["die_area_um2"] / 1.0e6
    return f"""- **Claim**: the committed crypto_rot_top gate-level netlist (`{NETLIST}`, {netlist['content_hash']}) was placed through clock-tree synthesis by the committed `klt place-and-route` request (`{REQUEST}`) with its stage bound derived to `target_stage: "cts"` (the derived document's only deltas: the stage and the netlist path re-anchored to the derived document's own directory -- verified by hash to name the same committed bytes), through OpenROAD's floorplan -> global/detailed placement -> clock-tree synthesis, on `sky130_fd_sc_hd` at liberty corner `tt_025C_1v80`, with the PDN (`power.preset` `sky130hd`) and tap cells placed and **no scan insertion performed** (the request carries no scan step and klt place-and-route emits none; spec/target-spec.md section 5 keeps v1 scan-free, decision record 0008). This is a **placed-through-CTS** claim and nothing beyond it: no route was run, no GDS exists, no DEF is committed, and T1 item 2 stays `unmet` / `no_evidence` -- the detailed route, its artifacts and its attestation are #47's. No security, key-isolation, side-channel, timing or certification claim is made (spec section 8).
- **Design provenance**: `klt synthesize`'s committed netlist (yosys -> `sky130_fd_sc_hd`, `tt_025C_1v80`, toplevel `{pnr['hdl_toplevel']}`), placed as-is; the freshness guard (`{CHECK_FRESH}`) re-synthesized and byte-compared it in this same invocation and passed: "{ctx.freshness}". CTS inserts clock buffers and the stage may resize gates, so the placed design's instance count exceeds the netlist's -- the count below is read from the run's own CTS DEF (`{ctx.cts_def_rel}`, {ctx.cts_def_hash}), not derived from either netlist.
- **Run configuration**: `./scripts/setup-env.sh`, then `./flow/pnr/crypto_rot_top/run.sh --through-cts --record` (the documented cold-start interface; ~25 min effectively single-threaded OpenROAD on a fleet host: freshness ~2 min, floorplan ~1, placement ~21, CTS ~2). Floorplan: utilization method at {ctx.utilization_pct} % (the spec section 7 budget row's utilization), site `unithd`, 5 um core margin; clock constraint `clk` at {ctx.clock_ns} ns (the section 7 core-clock target); I/O pins on met2/met3; seed {pnr['seed']}. klt scratch lives under `flow/build/pnr/crypto_rot_top/.klt/` (gitignored, next to the derived request). `run.sh --record` (bare) is the full-route contract: explicit `--backend batch` with `batch.job_timeout_s` sized above the measured route time, refused on a pin without single-unit batch -- nothing local starts by default.
- **Statistical convention**: deterministic (seeded request, pinned tools); no statistical row of the spec is touched, and this record satisfies no section 7 row: the area figures below are data against the placeholder budget, not a met row.
- **Result**: placed through CTS. {ctx.instances} placed instances (COMPONENTS in the CTS DEF, CTS buffers included); die {die_mm2:.4f} mm^2, core {core_mm2:.4f} mm^2, utilization {pnr['utilization_pct']} %; power delivery `{placed.get('status')}` (tapcells {placed.get('tapcells')}, endcaps {placed.get('endcaps')}, special nets {placed.get('special_nets')}). {_timing_note(pnr, ctx.clock_ns)}. Response warnings: {pnr.get('warnings') or 'none'}.

  Against the spec section 7 placeholder budget row -- {_spec_row()} -- the measured core is {core_mm2:.4f} mm^2 at {pnr['utilization_pct']} % utilization: reported data, not a met row. The row's own wording makes the 0.50 mm^2 budget a placeholder "to be re-set from the first SYNTH report" (the fallback 0.75 mm^2 likewise), so the measurement exceeding it is a fact for the spec process, not a failure of this run: re-setting the budget is a decision record on the spec (out of scope here, tracker #3).
- **Key-isolation status**: unchanged by this record. The netlist placed is the committed pre-CTS one whose netlist-level properties (`verification/records/crypto-rot-top-netlist-formal/`) stand as re-proven there; no scan/test/DFT step exists anywhere in this flow (the request requests none and klt place-and-route emits none), so nothing in it opened a path to a key. What a floorplan and CTS do to those properties is a question about the routed artifact (#47's post-route netlist, #49's LVS), deliberately not claimed here.
- **Not claimed**: no detailed route and no GDS (#47; T1 item 2 stays `unmet`), no DRC (#48), no LVS (#49), no STA or timing closure (#50 -- every slack figure above is a pre-route estimate at best), no power-delivery ERC (#53), no re-setting of the spec area budget, and no certification/validation/side-channel/entropy statement of any kind.
{ctx.tools_bullet}
- **Links**: `{REQUEST}`, `{NETLIST}`, `{NETLIST_ENVELOPE}`, `{CHECK_FRESH}`, `flow/pnr/crypto_rot_top/run.sh` (the stage-bound driver), `spec/target-spec.md` sections 5 and 7, issues #295 (this), #47 (the route), #48, #49, #50, #53, tracker #3.
"""


def write_record(args, pnr: dict, freshness: str) -> int:
    netlist = _netlist_meta(pnr)
    cts_def = _cts_def(pnr)
    prov = pnr["provenance"]
    request = json.loads((REPO / REQUEST).read_text())
    versions = rc.tool_versions()
    versions["klt"] = prov["klt_version"]
    versions["openroad"] = f"{pnr['engine']} {pnr['engine_version']}"
    tools_bullet = (
        f"- **Tool versions**: klt `{versions['klt']}` (pin `{versions['klt_pin']}`); "
        f"OpenROAD `{versions['openroad']}` (host install -- docs/environment.md; "
        "not content-pinned); the placed netlist was synthesized by yowasp-yosys "
        f"{versions['yowasp_yosys']} (`yosys.wasm` {versions['yosys_wasm']}); "
        f"PDK `{prov['pdk']['name']}` at open_pdks revision `{prov['pdk']['version']}`; "
        f"liberty `{prov['deck']['name']}` {prov['deck']['content_hash']}; "
        f"ciel {versions['ciel']}; Python {versions['python']}."
    )
    meta_extra = {
        "netlist": netlist,
        "request": {"path": REQUEST, "content_hash": sha256_file(REPO / REQUEST)},
        "cts_def": {"path": str(cts_def.relative_to(REPO)),
                    "content_hash": sha256_file(cts_def),
                    "placed_instances": count_def_components(cts_def)},
        "stage": {"target_stage": "cts", "stage_reached": pnr["stage_reached"]},
        "metrics": {key: pnr.get(key) for key in (
            "die_area_um2", "core_area_um2", "utilization_pct",
            "wirelength_um", "worst_slack_ns", "clock_skew_ns",
        )},
        "power_placed": pnr["power"]["placed"],
        "klt_version": prov["klt_version"],
        "openroad_engine_version": pnr["engine_version"],
        "pdk": {"name": prov["pdk"]["name"], "version": prov["pdk"]["version"]},
        "deck": {"name": prov["deck"]["name"],
                 "content_hash": prov["deck"]["content_hash"]},
        "tool_versions": versions,
    }
    ctx = SimpleNamespace(
        pnr=pnr, netlist=netlist, freshness=freshness,
        cts_def=cts_def,
        cts_def_rel=str(cts_def.relative_to(REPO)),
        cts_def_hash=sha256_file(cts_def),
        instances=count_def_components(cts_def),
        utilization_pct=request["floorplan"]["utilization_pct"],
        clock_ns=request["constraints"]["clock_period_ns"],
        tools_bullet=tools_bullet,
    )
    rc.check_pdk(args.pdk_root)
    rev = rc.require_clean_inputs(INPUTS, generator=__file__)
    rc.write_record(EXPERIMENT, rev, INPUTS, meta_extra,
                    record_body(ctx), generator=__file__)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--pdk-root", type=Path, required=True)
    args = ap.parse_args()
    pnr, freshness = _load_run()
    return write_record(args, pnr, freshness)


if __name__ == "__main__":
    sys.exit(main())
