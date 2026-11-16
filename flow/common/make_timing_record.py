#!/usr/bin/env python3
"""Write the append-only record for the cores' pre-layout setup-timing flow
(`verification/rtl/aes/run.sh --timing` and the sha256 equivalent).

Reads flow/build/<core>/sta-synth.json (the `klt synthesize` response at the
ss corner) and flow/build/<core>/sta.json (the `klt sta` response) each
core's --timing mode wrote, and records one row per core: corner, clock
period, worst setup slack, the critical path's start and end points, and the
liberty hash. Refuses to record unless both runs completed and unless every
input each run stamped as measured (flow/build/<core>/sta-inputs.json, written
by core_flow_sta_inputs) still hashes to its stamped value -- either core's
--timing leaves scratch behind and the other core's --record consumes it, so
without that stamp a record could carry one core's revision-Y git_revision
with the other revision's number.

This drives record_lib's lower-level helpers directly (check_pdk,
require_clean_inputs, tool_versions, write_record), not main(): main() is the
sim+synth entry point -- it unconditionally reads sim.json and synth.json
from --out-dir and computes a simulation-and-synthesis verdict from them
(flow/common/record_lib.py), none of which a timing-only run produces. The
formal flow reached the same conclusion for the same reason
(verification/formal/make_record.py). Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import record_lib as rc  # noqa: E402

EXPERIMENT = "core-pre-layout-sta"
#: Per core: the directory under verification/rtl/, the `klt synthesize`
#: response, and the `klt sta` response -- both written by that run.sh's
#: --timing mode, newest superseding per experiment: one record, a row per core.
CORES = (
    ("aes", "aes_core", "flow/build/aes/sta-synth.json", "flow/build/aes/sta.json"),
    ("sha256", "sha256_core", "flow/build/sha256/sta-synth.json", "flow/build/sha256/sta.json"),
)
# The inputs OUTSIDE this directory. The tracked files beside this generator
# are derived by record_lib.own_inputs(), the shared flow helpers by
# shared_inputs() -- listing the two run.sh files here is what makes
# shared_inputs() pick core_flow.sh up (issues #124, #146).
INPUTS = (
    "rtl/aes/aes_core.v",
    "rtl/sha256/sha256_core.v",
    "verification/rtl/aes/run.sh",
    "verification/rtl/aes/sta-request.json",
    "verification/rtl/aes/sta-synth-request.json",
    "verification/rtl/sha256/run.sh",
    "verification/rtl/sha256/sta-request.json",
    "verification/rtl/sha256/sta-synth-request.json",
)


def _load_run_outputs() -> list[tuple[str, str, dict, dict]]:
    """(core dir, toplevel, sta-synth response, sta response) per core,
    refusing unless every analysis completed and every input the run stamped
    into sta-inputs.json still hashes to its stamped value."""
    out = []
    for core, top, synth_rel, sta_rel in CORES:
        for rel in (synth_rel, sta_rel):
            if not (rc.REPO / rel).exists():
                print(f"timing: not recording, {rel} is missing -- run "
                      f"verification/rtl/{core}/run.sh --timing first", file=sys.stderr)
                raise SystemExit(1)
        synth = json.loads((rc.REPO / synth_rel).read_text())
        sta = json.loads((rc.REPO / sta_rel).read_text())
        if synth.get("status") != "ok" or sta.get("status") != "ok":
            print(f"timing: not recording, {core} did not complete "
                  f"(synthesis {synth.get('status')!r}, sta {sta.get('status')!r})",
                  file=sys.stderr)
            raise SystemExit(1)
        # A completed analysis is not automatically a measurement: a wrong
        # clock port still exits 0 but times nothing -- timing_status
        # "unconstrained", slack fields at OpenSTA's 1e+39 sentinel,
        # constraint_completeness "incomplete". Refuse; never quote a
        # sentinel as a slack number.
        if sta.get("timing_status") != "constrained":
            print(f"timing: not recording, {core} timing_status is "
                  f"{sta.get('timing_status')!r} -- the clock constraint "
                  "constrained no path; check sta-request.json's clock_port "
                  "and the response's constraint_completeness", file=sys.stderr)
            raise SystemExit(1)
        # A completed, constrained analysis is not automatically a fresh one:
        # either core's run.sh --timing leaves its scratch behind and this
        # --record consumes the OTHER core's, so the engine and liberty-deck
        # checks above and in main() cannot see a run that went stale across
        # an RTL or request change within one tool and deck generation. The
        # run stamped what it measured into sta-inputs.json
        # (core_flow_sta_inputs); recompute every stamped hash and refuse on
        # the first file that changed since, naming it and the core to
        # re-run. The stamped head is diagnostic only -- HEAD moves for
        # reasons unrelated to these files, so the content hashes are the
        # comparison (issue #218).
        side = rc.REPO / "flow/build" / core / "sta-inputs.json"
        if not side.exists():
            print(f"timing: not recording, {side.relative_to(rc.REPO)} is "
                  "missing -- scratch from before input stamping is stale by "
                  f"definition; re-run verification/rtl/{core}/run.sh --timing "
                  "first", file=sys.stderr)
            raise SystemExit(1)
        try:
            stamped = {entry["path"]: entry["content_hash"]
                       for entry in json.loads(side.read_text())["inputs"]}
            if not stamped:
                raise KeyError("inputs")
        except (json.JSONDecodeError, KeyError, TypeError):
            print(f"timing: not recording, {side.relative_to(rc.REPO)} is not "
                  "a readable input stamp; re-run "
                  f"verification/rtl/{core}/run.sh --timing first", file=sys.stderr)
            raise SystemExit(1)
        for rel, old in sorted(stamped.items()):
            path = rc.REPO / rel
            if not path.exists():
                print(f"timing: not recording, {rel} is stamped in {core}'s "
                      "sta-inputs.json but does not exist; re-run "
                      f"verification/rtl/{core}/run.sh --timing first", file=sys.stderr)
                raise SystemExit(1)
            new = rc.sha256(path)
            if new != old:
                print(f"timing: not recording, {core} was timed before {rel} "
                      f"changed (stamped {old}, now {new}); re-run "
                      f"verification/rtl/{core}/run.sh --timing first", file=sys.stderr)
                raise SystemExit(1)
        out.append((core, top, synth, sta))
    return out


def _clock_period_ns() -> str:
    """The clock constraint the timed runs applied, read back from the
    committed sta-request.json files rather than restated from memory."""
    seen = set()
    for path in INPUTS:
        if path.endswith("/sta-request.json"):
            request = json.loads((rc.REPO / path).read_text())
            seen.add(request["constraints"]["clock_period_ns"])
    if len(seen) != 1:
        raise SystemExit(f"the sta requests disagree on clock_period_ns: {sorted(seen)}")
    return str(seen.pop())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root", type=Path, required=True)
    args = ap.parse_args()

    runs = _load_run_outputs()
    rc.check_pdk(args.pdk_root)
    rev = rc.require_clean_inputs(INPUTS, generator=__file__)
    versions = rc.tool_versions()
    # Yosys synthesized every netlist; the STA engine comes from the sta
    # responses' own fields, never by shelling out: these are the builds the
    # numbers were produced with.
    yosys = {synth["engine_version"] for _, _, synth, _ in runs}
    engines = {f"{sta['engine']} {sta.get('engine_version') or 'unknown'}"
               for _, _, _, sta in runs}
    if len(yosys) != 1 or len(engines) != 1:
        raise SystemExit(f"the runs disagree on tool builds: yosys {yosys}, sta {engines}")
    versions["yosys"] = yosys.pop()
    versions["sta_engine"] = engines.pop()

    period = _clock_period_ns()
    rows = []
    per_core_provenance = []
    decks = set()
    for core, top, synth, sta in runs:
        prov = sta["provenance"]
        decks.add((prov["deck"]["name"], prov["deck"]["content_hash"]))
        path_ = sta["worst_setup_path"]
        rows.append(
            f"  | `{top}` (`{core}`) | {prov['deck']['name'].split('__')[-1]} | {period} | "
            f"{sta['worst_slack_ns']} | {sta['total_negative_slack_ns']} | "
            f"{sta['setup_violation_count']} | {sta['fmax_mhz']} | "
            f"{sta['timing_status']} | `{path_['startpoint']}` -> "
            f"`{path_['endpoint']}` ({path_['slack_ns']} ns) | "
            f"`{prov['deck']['content_hash']}` |")
        per_core_provenance.append(
            f"  - `{top}`: klt `{prov['klt_version']}`, pdk `{prov['pdk']['name']}` "
            f"{prov['pdk']['version']}, liberty `{prov['deck']['name']}` "
            f"{prov['deck']['content_hash']}, synthesis input "
            f"{prov['input']['content_hash']} ({synth['instance_count']} instances).")
    if len(decks) != 1:
        raise SystemExit(f"the two runs were not timed against one liberty deck: {decks}")

    table = "\n".join(rows)
    provenance = "\n".join(per_core_provenance)
    body = f"""- **Claim**: a measurement, not a pass/fail: the worst **setup** slack each of `rtl/aes/aes_core.v` and `rtl/sha256/sha256_core.v` shows at the corner and clock period in the table below, on the netlist `klt synthesize` produced from that core's committed `sta-synth-request.json`, timed by `klt sta` in DEF-free `verilog` mode against the committed `sta-request.json`. Whatever the numbers are -- positive or negative -- they are the reported data; `klt sta` has no pass/fail concept of its own and this record claims none. This record satisfies **no** `spec/target-spec.md` section 7 row: the spec's timing rows are targets for post-route timing at their own corners, and this is a pre-layout single-corner estimate of two cores only. The spec's 50 MHz / 20 ns setup bind at `ss_100C_1v60` is the question being measured, not a row being met; T1 item 5 stays unmet until the multi-corner, post-route work of #50.
- **Design provenance**: synthesized gate-level netlists (yosys -> `sky130_fd_sc_hd`), timed before place-and-route.
- **Run configuration**: `./scripts/setup-env.sh`, then `./verification/rtl/aes/run.sh --timing --record` and `./verification/rtl/sha256/run.sh --timing --record` (either `--record` invocation writes this record; both runs' `sta.json` must exist). Per core: `klt synthesize verification/rtl/<core>/sta-synth-request.json --pdk sky130A` at liberty corner `ss_100C_1v60` with a {period} ns clock target (the committed `synth-request.json` runs are untouched evidence of their own tt run), then `klt sta` on that netlist -- a structural gate-level netlist linked with `read_lef`/`read_verilog`/`link_design` and timed against liberty plus `constraints.clock_port`/`clock_period_ns` alone. Single corner; no placement, no routing, no CTS.
- **Result**: both analyses completed (`status` `ok`).

  | core | corner | clock period (ns) | worst setup slack (ns) | total negative slack (ns) | setup violations | fmax (MHz) | timing status | worst setup path | liberty hash |
  |---|---|---|---|---|---|---|---|---|---|
{table}

  `timing status` `constrained` means the slack fields are measurements at the stated constraint, not OpenSTA's unconstrained sentinel. The worst path's startpoint -> endpoint pair is per core in the table; the full per-hop breakdown stays in the run's `sta.json` (build scratch, not tracked evidence).
- **Pre-layout labelling**: every row above is `geometry_source: netlist_estimate` -- a gate-level estimate with **no wire parasitics**: no DEF, no SPEF, no extraction. No wire-load model was requested, so the responses echo `wire_load_model: null` / `wire_load_mode: null` and OpenSTA applies its own ideal treatment of the netlist's wires; the wire load is an assumption of the mode, not an absence of one, and a post-route number will differ from these for that reason alone.
- **Hold**: the same responses carry hold-slack fields; they are deliberately quoted nowhere above. Hold analysis is out of scope here, and `ss_100C_1v60` is not the hold-binding corner -- `spec/target-spec.md` section 7 binds hold at `ff_n40C_1v95` -- so no hold claim is made or implied.
- **Spec status**: nothing here edits or satisfies `spec/target-spec.md`, and no "met" is claimed for T1 item 5. The AES datapath of decision record 0004 is not being judged by this number: a miss is a reported measurement, and any datapath response goes through a decision record (#50, #82 and #87 inherit whatever this reports).
- **Tool versions**: klt `{versions['klt_pin']}`, yowasp-yosys {versions['yowasp_yosys']} (`yosys.wasm` {versions['yosys_wasm']}), STA engine {versions['sta_engine']}, ciel {versions['ciel']}, Python {versions['python']}.
- **Per-core provenance** (the simulation tools in the pinned venv are listed in the sim+synth records; no simulation ran for this one):
{provenance}
- **Links**: `rtl/aes/`, `rtl/sha256/`, `verification/rtl/aes/`, `verification/rtl/sha256/`, `docs/environment.md`, `spec/target-spec.md` section 7, #50 (the multi-corner, post-route successor), #87 (the top level that inherits these numbers).
- **Timestamp / author**: {{timestamp}}, Loom builder agent (issue #178).
"""
    first_prov = runs[0][3]["provenance"]
    rc.write_record(EXPERIMENT, rev, INPUTS, {
        "klt_version": first_prov["klt_version"],
        "pdk": {"name": first_prov["pdk"]["name"], "version": first_prov["pdk"]["version"]},
        "deck": {"name": first_prov["deck"]["name"], "content_hash": first_prov["deck"]["content_hash"]},
        "tool_versions": versions,
    }, body, generator=__file__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
