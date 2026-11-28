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

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from narco_module import current_module  # noqa: E402

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()
OWNERS = json.loads((ROOT / ".github" / "owners.json").read_text())
ENV_MODULE = os.environ.get("NARCO_MODULE", "").strip().upper()
BRANCH_MODULE = current_module(ROOT)
# The branch decides, as in CI; NARCO_MODULE is optional and must agree with it (#182).
MODULE = BRANCH_MODULE or ENV_MODULE

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
DOC_HOSTS = ("readthedocs", "docs.", "pysal.org", "github.com", "pypi.org", "python.org",
             "scipy.org", "statsmodels.org", "pandas.pydata.org", "numpy.org", "geopandas.org",
             "shapely.", "pyproj4.github.io", "scikit-image.org", "dataspace.copernicus.eu",
             "globalfishingwatch.org", "openeo.org", "ecmwf.int")


def scratch(path_str: str) -> bool:
    """A throwaway file outside the repo: under $NARCO_SCRATCH, or a Claude Code session scratchpad
    (/tmp/claude-<uid>/.../scratchpad/...). It cannot touch the repo, so any module may write it (#106)."""
    p = Path(path_str).resolve()
    roots = [Path(os.environ["NARCO_SCRATCH"]).resolve()] if os.environ.get("NARCO_SCRATCH") else []
    if any(p == r or r in p.parents for r in roots):
        return True
    parts = p.parts
    return (len(parts) > 3 and parts[1] == "tmp" and parts[2].startswith("claude-")
            and "scratchpad" in parts[3:-1])


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


def belongs_to_another_module(r: str) -> bool:
    for other, info in OWNERS["modules"].items():
        if other == MODULE:
            continue
        if any(r == p.rstrip("/") or r.startswith(p) for p in info["paths"]):
            return True
    return False


def shell_write_targets(cmd: str) -> list[str]:
    """Best-effort list of paths a shell command would create or overwrite."""
    targets: list[str] = []
    for m in re.finditer(r"&?>>?\s*([^\s;&|<>]+)", cmd):
        targets.append(m.group(1))
    for m in re.finditer(r"(?<![\w./-])(tee|touch|mkdir|rm|cp|mv)\b([^;&|]*)", cmd):
        targets += [a.strip("'\"") for a in m.group(2).split() if not a.startswith("-")]
    for m in re.finditer(r"(?<![\w./-])(sed|perl)\b([^;&|]*)", cmd):
        if re.search(r"(?:^|\s)-[A-Za-z]*i\b", m.group(2)):
            targets += [a.strip("'\"") for a in m.group(2).split()
                        if not a.startswith("-") and not a.startswith(("'", '"'))]
    return [t for t in targets
            if t and not t.startswith(("/dev/", "&", "~")) and "$" not in t]


def main() -> None:
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
    inp = data.get("tool_input", {}) or {}

    if tool in EDIT_TOOLS:
        target = inp.get("file_path") or inp.get("notebook_path") or ""
        if rel(target) is None and scratch(target):
            return
        if ENV_MODULE and BRANCH_MODULE and ENV_MODULE != BRANCH_MODULE:
            block(f"NARCO_MODULE={ENV_MODULE} but this worktree's branch belongs to "
                  f"{BRANCH_MODULE}. Unset NARCO_MODULE or use the right worktree.")
        if MODULE not in OWNERS["modules"]:
            block("work in a mod/p<n>/<issue> worktree (scripts/new_task.sh, see AGENTS.md).")
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
        if re.search(r"git\s+push\b[^;&|]*?(?:^|\s|:)(main|integration)(?=\s|$)", cmd):
            block("push your mod/<module>/<issue> branch and open a PR; never push to main or integration.")
        env_tokens = re.findall(r"(?<![\w./-])(\.env(?:\.[\w.-]+)?)(?![\w.-])", cmd)
        if any(t != ".env.example" for t in env_tokens):
            block("secrets files are never read by agents.")
        for target in shell_write_targets(cmd):
            r = rel(target)
            if r is not None and not path_ok(r) and belongs_to_another_module(r):
                block(f"{MODULE} may not write {r} from the shell. Open an issue on the owning module instead.")
        if MODULE not in OWNERS["network_allowed"] and re.search(r"(^|[;&|\s])(curl|wget)\s", cmd):
            block(f"{MODULE} has no network access; only ingest downloads data.")

    elif tool == "WebFetch":
        url = inp.get("url", "")
        if MODULE not in OWNERS["network_allowed"] and not any(h in url for h in DOC_HOSTS):
            block("only documentation sites may be fetched outside ingest.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # fail closed: a broken guard must not let edits through (#182)
        block(f"guard error ({type(e).__name__}: {e}).")
