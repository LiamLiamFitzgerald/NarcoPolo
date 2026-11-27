#!/usr/bin/env python3
"""Create one GitHub issue per function group in each module's pseudo-codebase, plus one stub issue per module.

Dry run by default (prints what it would create). Add --apply to create the issues with gh.
Usage: python3 scripts/seed_issues.py [--apply] [--module P4]
"""

import argparse
import re
import subprocess
from pathlib import Path

GROUP = re.compile(r"^([a-z_]+/[A-Za-z_]*)")  # e.g. "detect/cfar", "aggregate/", "dashboard/"


def parse(module: str) -> tuple[list[tuple[str, str]], str]:
    text = Path(f"docs/specs/{module}.md").read_text()
    block = re.search(r"```text\n(.*?)```", text, re.S)
    groups: list[tuple[str, list[str]]] = []
    for line in (block.group(1) if block else "").splitlines():
        m = GROUP.match(line)
        if m:
            groups.append((m.group(1).rstrip("/") or m.group(1), [line]))
        elif groups and line.strip():
            groups[-1][1].append(line)
    tests = re.search(r"### Tests \(done when\)\n(.*?)(\n### |\Z)", text, re.S)
    return [(g, "\n".join(body)) for g, body in groups], (tests.group(1).strip() if tests else "")


def issues_for(module: str) -> list[tuple[str, str, list[str]]]:
    groups, tests = parse(module)
    out = []
    stub_list = "\n".join(f"- `{g}`" for g, _ in groups)
    out.append((
        f"[{module}] Stubs for every public function (due Fri 22:00)",
        f"Create every public function from the pseudo-codebase in `docs/specs/{module}.md` as a stub that "
        f"returns schema-valid simulator output, so `make all` runs end to end on the simulator by Saturday 02:00.\n\n"
        f"Groups:\n{stub_list}\n\nDone when: `make sim && make all` runs with these stubs; schemas pass.",
        [f"module:{module}", "task", "stub"],
    ))
    for group, body in groups:
        out.append((
            f"[{module}] Implement {group}",
            f"Spec: `docs/specs/{module}.md` (pseudo-codebase block, group `{group}`). "
            f"Read the module's Steps, Warnings and the shared Review passes table first.\n\n"
            f"```text\n{body}\n```\n\n"
            f"Done when: the `test:` lines above (if any) pass on the simulator, plus the relevant items from the "
            f"module's Tests list:\n\n{tests}\n",
            [f"module:{module}", "task"],
        ))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--module")
    a = ap.parse_args()
    modules = [a.module.upper()] if a.module else [f"P{n}" for n in range(1, 8)]
    total = 0
    for module in modules:
        for title, body, labels in issues_for(module):
            total += 1
            if a.apply:
                cmd = ["gh", "issue", "create", "--title", title, "--body", body]
                for lab in labels:
                    cmd += ["--label", lab]
                subprocess.run(cmd, check=True)
            else:
                print(f"- {title}   [{', '.join(labels)}]")
    print(f"\n{total} issues {'created' if a.apply else 'would be created (dry run; add --apply)'}")


if __name__ == "__main__":
    main()
