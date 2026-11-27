#!/usr/bin/env python3
"""Claude Code PreToolUse guard.

Blocks (exit code 2, reason on stderr, which Claude sees):
- edits outside the folders owned by this agent's module (NARCO_MODULE=P1..P7)
- network commands and web fetches for modules without network access
- pushes to main or integration, and force pushes
- reading secrets files
"""

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()
OWNERS = json.loads((ROOT / ".github" / "owners.json").read_text())
MODULE = os.environ.get("NARCO_MODULE", "").upper()

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
DOC_HOSTS = ("readthedocs", "docs.", "pysal.org", "github.com", "pypi.org", "python.org",
             "scipy.org", "statsmodels.org", "pandas.pydata.org", "numpy.org", "geopandas.org",
             "shapely.", "pyproj4.github.io", "scikit-image.org", "dataspace.copernicus.eu",
             "globalfishingwatch.org", "openeo.org", "ecmwf.int")


def block(reason: str) -> None:
    print(f"Blocked by NarcoPolo guard: {reason}", file=sys.stderr)
    sys.exit(2)


def allowed_paths() -> list[str]:
    mod = OWNERS["modules"].get(MODULE)
    return (mod["paths"] if mod else []) + OWNERS["shared"]


def rel(path_str: str) -> str | None:
    p = Path(path_str)
    if not p.is_absolute():
        p = Path.cwd() / p
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return None


def path_ok(r: str) -> bool:
    for a in allowed_paths():
        if a.endswith("/") and (r + "/").startswith(a):
            return True
        if r == a:
            return True
    return False


def main() -> None:
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
    inp = data.get("tool_input", {}) or {}

    if tool in EDIT_TOOLS:
        if MODULE not in OWNERS["modules"]:
            block("set NARCO_MODULE=P1..P7 before starting Claude Code (see AGENTS.md).")
        target = inp.get("file_path") or inp.get("notebook_path") or ""
        r = rel(target)
        if r is None:
            block(f"{target} is outside the repository.")
        if not path_ok(r):
            block(f"{MODULE} may not edit {r}. Open an issue on the owning module instead "
                  f"(owners in .github/owners.json).")

    elif tool == "Read":
        name = Path(inp.get("file_path", "")).name
        if name == ".env" or name.startswith(".env.") and name != ".env.example":
            block("secrets files are never read by agents.")

    elif tool == "Bash":
        cmd = inp.get("command", "")
        if re.search(r"git\s+push\b.*(--force|\s-f\b)", cmd):
            block("force pushes are not allowed.")
        if re.search(r"git\s+push\b.*\b(main|integration)\b", cmd):
            block("push your mod/<module>/<issue> branch and open a PR; never push to main or integration.")
        if re.search(r"(^|[;&|\s])(cat|less|head|tail)\s+[^;&|]*\.env(\s|$)", cmd):
            block("secrets files are never read by agents.")
        if MODULE not in OWNERS["network_allowed"] and re.search(r"(^|[;&|\s])(curl|wget)\s", cmd):
            block(f"{MODULE} has no network access; only ingest downloads data.")

    elif tool == "WebFetch":
        url = inp.get("url", "")
        if MODULE not in OWNERS["network_allowed"] and not any(h in url for h in DOC_HOSTS):
            block("only documentation sites may be fetched outside ingest.")


if __name__ == "__main__":
    main()
