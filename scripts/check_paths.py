#!/usr/bin/env python3
"""CI: a PR from branch mod/p<n>/<issue> may only change files owned by P<n> (plus shared files).

Usage: check_paths.py <head-branch> <base-ref>
"""

import json
import subprocess
import sys
from pathlib import Path

from narco_module import module_from_branch  # scripts/ is on sys.path

owners = json.loads(Path(".github/owners.json").read_text(encoding="utf-8"))
branch, base = sys.argv[1], sys.argv[2]

module = module_from_branch(branch)
if not module:
    print(f"Branch {branch!r} is not a module branch (mod/p<n>/<issue>); ownership check skipped.")
    sys.exit(0)

allowed = owners["modules"][module]["paths"] + owners["shared"]
changed = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"],
                         capture_output=True, text=True, check=True).stdout.split()


def ok(path: str) -> bool:
    return any(path == a or (a.endswith("/") and path.startswith(a)) for a in allowed)


bad = [p for p in changed if not ok(p)]
if bad:
    print(f"{module} branch changes files it doesn't own:")
    for p in bad:
        print(f"  {p}")
    print("Open an issue on the owning module instead (owners in .github/owners.json).")
    sys.exit(1)
print(f"{module}: all {len(changed)} changed files are inside its folders.")
