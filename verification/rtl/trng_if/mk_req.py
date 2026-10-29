#!/usr/bin/env python3
"""Regenerate the klt request files in this directory (stdlib only)."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RTL = ["../../../rtl/aes/aes_core.v", "../../../rtl/drbg/ctr_drbg.v",
       "../../../rtl/trng_if/trng_if.v", "../../../rtl/drbg/drbg_top.v"]


def req(srcs, top, mod, defines=None, tc=None):
    opt = {"coverage": False, "timescale": ["1ns", "1ps"], "random_seed": 1}
    if defines:
        opt["defines"] = {k: None for k in defines}
    return {"schema": "klt.functional_verification.request/1", "engine": "icarus",
            "sources": srcs, "hdl_toplevel": top, "testbench": ({"module": mod, "testcase": tc} if tc else {"module": mod}),
            "options": opt}


IF = ["../../../rtl/trng_if/trng_if.v", "tb_trng_if.v"]
SYS = RTL + ["tb_sys.v"]
REAL = SYS + ["../../../flow/build/trng/trng_digital.v"]
OUT = {
    "sim-if-request": req(IF, "tb_trng_if", "test_trng_if"),
    "sim-if-negctl-prev-request": req(IF, "tb_trng_if", "test_trng_if", ["TRNG_IF_NEG_PREV"]),
    "sim-if-negctl-discard-request": req(IF, "tb_trng_if", "test_trng_if", ["TRNG_IF_NEG_DISCARD"]),
    "sim-if-negctl-count-request": req(IF, "tb_trng_if", "test_trng_if", ["TRNG_IF_NEG_COUNT"]),
    "sim-sys-request": req(SYS, "tb_sys", "test_sys", tc="test_sys"),
    "sim-sys-negctl-zeroize-request": req(SYS, "tb_sys", "test_sys", ["DRBG_NEG_ZEROIZE"], "test_sys"),
    "sim-sys-negctl-interval-request": req(SYS, "tb_sys", "test_sys", ["DRBG_NEG_INTERVAL"], "test_sys"),
    "sim-real-request": req(REAL, "tb_sys", "test_sys", ["REAL_TRNG"], "test_sys_real"),
}
for name, doc in OUT.items():
    (HERE / f"{name}.json").write_text(json.dumps(doc, indent=2) + "\n")
