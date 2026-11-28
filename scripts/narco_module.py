#!/usr/bin/env python3
"""The module (P1..P7) is the branch name: mod/p<n>/<issue>. guard.py, check_paths.py and the
commit-msg hook all use this, so they can't disagree (#182). Run as a script it prints the module."""

import re
import subprocess
import sys
from pathlib import Path

PATTERN = re.compile(r"mod/p([1-7])/", re.IGNORECASE)


def module_from_branch(branch: str) -> str | None:
    m = PATTERN.match(branch.strip())
    return f"P{m.group(1)}" if m else None


def current_module(repo: Path | str = ".") -> str | None:
    r = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return module_from_branch(r.stdout) if r.returncode == 0 else None


if __name__ == "__main__":
    print(current_module(sys.argv[1] if len(sys.argv) > 1 else ".") or "")
