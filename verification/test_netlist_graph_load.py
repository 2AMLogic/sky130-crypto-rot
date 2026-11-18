"""The P-12 flow's top-module selection is by exact name, provably (issue #281).

PR #280 unified the cone helpers into netlist_graph.load() and adopted the
keyladder copy's looser semantics: a module carrying the Yosys `top' attribute
is accepted even when it is not the module the caller named, and a missing
named top stops the run only if no other module claims the attribute. Harmless
on today's flow output (flatten leaves exactly one module), but this is the
key-isolation proof tooling: the guarantee that was lost is exactly "the cone
check provably ran on the module we named". load() now takes strict=True --
name-only selection, hard stop otherwise -- and cone_p12.py passes it; the
keyladder flow keeps the attribute fallback, unchanged.

The full flows are local-only (PDK, pinned yosys -- see verification/README.md),
so this pins the selection contract directly on hand-built netlist JSONs, the
way test_gen_netlist_binding.py pins the generator's binding contract.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LOADER = "verification/formal/netlist_graph.py"


@pytest.fixture(scope="module")
def ng():
    spec = importlib.util.spec_from_file_location("formal_netlist_graph", REPO / LOADER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["formal_netlist_graph"] = mod
    spec.loader.exec_module(mod)
    return mod


def write_netlist(tmp_path: Path, modules: dict) -> str:
    p = tmp_path / "flat.json"
    p.write_text(json.dumps({"modules": modules}))
    return str(p)


def module(attributes: dict | None = None) -> dict:
    return {"attributes": attributes or {}, "cells": {}, "netnames": {}, "ports": {}}


# --- strict=True: the returned module is the one we named --------------------


def test_strict_returns_the_named_module_not_a_decoy(ng, tmp_path):
    # The decoy carries the Yosys `top' attribute but a different name, both
    # before and after the real module (the old last-match-wins loop would
    # return the decoy when it came last). The named module carries no
    # attributes, so any decoy adoption shows in the attributes dict.
    path = write_netlist(tmp_path, {
        "crypto_rot_decoy": module({"top": 1}),
        "crypto_rot_top": module(),
        "crypto_rot_decoy_last": module({"top": 1}),
    })
    assert ng.load(path, "crypto_rot_top", strict=True)["attributes"] == {}


def test_strict_exits_on_a_missing_named_top_even_with_a_decoy(ng, tmp_path):
    # The old behavior: the decoy's `top' attribute would be silently adopted
    # and the cone check would run on a module we never named.
    path = write_netlist(tmp_path, {"crypto_rot_decoy": module({"top": 1})})
    with pytest.raises(SystemExit) as exc:
        ng.load(path, "crypto_rot_top", strict=True)
    msg = str(exc.value.code)
    assert "crypto_rot_top" in msg and str(path) in msg


def test_strict_still_selects_by_name_when_no_attribute_exists(ng, tmp_path):
    path = write_netlist(tmp_path, {"crypto_rot_top": module(), "other": module()})
    assert ng.load(path, "crypto_rot_top", strict=True) is not None


# --- default (strict=False): the keyladder attribute fallback, unchanged -----


def test_default_still_accepts_the_attribute_fallback(ng, tmp_path):
    path = write_netlist(tmp_path, {"some_other_name": module({"top": 1})})
    assert ng.load(path, "keyladder") is not None


def test_default_still_selects_by_name(ng, tmp_path):
    path = write_netlist(tmp_path, {"keyladder": module(), "other": module()})
    assert ng.load(path, "keyladder") is not None


def test_default_keeps_last_attribute_match_wins(ng, tmp_path):
    path = write_netlist(tmp_path, {"first": module({"marker": "first", "top": 1}),
                                    "second": module({"marker": "second", "top": 1})})
    assert ng.load(path, "keyladder")["attributes"]["marker"] == "second"


def test_default_exits_when_nothing_matches(ng, tmp_path):
    path = write_netlist(tmp_path, {"some_other_name": module()})
    with pytest.raises(SystemExit) as exc:
        ng.load(path, "keyladder")
    assert "keyladder" in str(exc.value.code)
