#!/usr/bin/env python3
"""Stage the inputs of the key ladder formal runs (issue #56). Standard library only.

Everything the SymbiYosys runs read is generated here, into one staging directory,
from the tracked RTL and the tracked property text. Nothing under rtl/ is edited:

  dut_rtl.v        rtl/keyladder/keyladder.v with props_slots.vh spliced in front of
                   its final `endmodule`. The splice is checked: removing the block
                   gives back the original bytes.
  mut_slotpath.v   rtl/keyladder/keyladder.v with ONE added slot -> non-key-output
                   path (`busy` ORs in s0[0]). The negative control for P-1 and P-2.
  dut_net*.v       the `keyladder` module of a klt-synthesized netlist with the same
                   property text spliced in (the other modules of the netlist are
                   dropped: the P-5/P-6 netlist runs use hmac_abstract.v instead).
  rtl_<v>.v        preprocessed RTL for the synthesis negative controls (-DKL_NEG_*).
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
RTL = REPO / "rtl/keyladder/keyladder.v"

# The one textual mutation of RTL that is not an existing `ifdef KL_NEG_*`.
SLOTPATH_FROM = "assign busy        = (state != S_IDLE);"
SLOTPATH_TO = "assign busy        = (state != S_IDLE) | s0[0];"


def splice(module_text: str, block: str, module: str) -> str:
    """Insert block before the `endmodule` that closes `module`."""
    m = re.search(rf"^module {re.escape(module)}\b", module_text, re.M)
    if not m:
        raise SystemExit(f"module {module} not found")
    end = module_text.index("\nendmodule", m.end())
    out = module_text[: end + 1] + block + "\n" + module_text[end + 1 :]
    # the splice must be a pure insertion
    assert out.replace(block + "\n", "", 1) == module_text, "splice altered the source"
    return out


def module_text(netlist: str, module: str) -> str:
    m = re.search(rf"^module {re.escape(module)}\b", netlist, re.M)
    if not m:
        raise SystemExit(f"module {module} not in netlist")
    end = netlist.index("\nendmodule", m.end()) + len("\nendmodule\n")
    return netlist[m.start() : end]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=Path, required=True)
    ap.add_argument("--netlist", action="append", default=[], metavar="NAME=PATH",
                    help="synthesized netlist variant, e.g. clean=...keyladder_synth.v")
    ap.add_argument("--preprocess", action="append", default=[], metavar="NAME=DEFINE",
                    help="write rtl_NAME.v = RTL preprocessed with -DDEFINE")
    args = ap.parse_args()
    st = args.stage
    st.mkdir(parents=True, exist_ok=True)

    props = (HERE / "props_slots.vh").read_text()
    rtl = RTL.read_text()
    (st / "dut_rtl.v").write_text(splice(rtl, props, "keyladder"))

    if rtl.count(SLOTPATH_FROM) != 1:
        raise SystemExit("slot-path mutation site not found exactly once; rtl changed?")
    (st / "mut_slotpath.v").write_text(rtl.replace(SLOTPATH_FROM, SLOTPATH_TO))

    for item in args.preprocess:
        name, define = item.split("=", 1)
        out = subprocess.run(["iverilog", "-E", f"-D{define}", "-o", str(st / f"rtl_{name}.v"),
                              str(RTL)], capture_output=True, text=True)
        if out.returncode != 0:
            raise SystemExit(out.stderr)

    for item in args.netlist:
        name, path = item.split("=", 1)
        net = Path(path).read_text()
        kl = module_text(net, "keyladder")
        (st / f"dut_net_{name}.v").write_text(splice(kl, props, "keyladder"))
        if Path(path).resolve() != (st / f"net_{name}.v").resolve():
            shutil.copyfile(path, st / f"net_{name}.v")

    for f in ("hmac_abstract.v", "p1_product.v"):
        shutil.copyfile(HERE / f, st / f)
    for f in ("rtl/hmac/hmac_sha256.v", "rtl/sha256/sha256_core.v", "rtl/keyladder/keyladder.v"):
        shutil.copyfile(REPO / f, st / Path(f).name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
