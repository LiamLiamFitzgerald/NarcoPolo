#!/usr/bin/env python3
"""make all: call run() of every pipeline module in order. Each run() takes no arguments, reads its inputs from
stage files and writes its outputs through core.io (DECISIONS.md, 2026-11-27 18:30)."""

import importlib

STEPS = ["reference", "coverage", "detect", "match", "aggregate", "forecast", "detectors", "fuse", "patrol", "export"]

for name in STEPS:
    mod = importlib.import_module(name)
    if not hasattr(mod, "run"):
        raise SystemExit(f"make all: module {name!r} has no run() yet (its stub issue defines it)")
    print(f"== {name}.run()", flush=True)
    mod.run()
