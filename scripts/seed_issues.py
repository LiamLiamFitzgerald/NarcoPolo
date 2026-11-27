#!/usr/bin/env python3
"""Create the GitHub issues: one per function group plus one stub issue per module, with
priority, milestone, build wave, dependencies, and a master issue holding the dependency map.

Dry run by default: prints the plan and writes docs/issue-plan.md. --apply creates everything
through the REST API (safe to rerun; existing titles are skipped). Needs `gh auth login` and repo write access.
Usage: python3 scripts/seed_issues.py [--apply]
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

GROUP = re.compile(r"^([a-z_]+/[A-Za-z_0-9]*)")  # e.g. "detect/cfar", "aggregate/"
M = {1: "M1 Contracts + simulator (Fri 22:00 to Sat 02:00)", 2: "M2 Real data cached (Sat 12:00)",
     3: "M3 End to end on real data (Sat 22:00)"}
DUE = {1: "2026-11-28T02:00:00Z", 2: "2026-11-28T12:00:00Z", 3: "2026-11-28T22:00:00Z"}
PRIO = {"critical": ("b60205", "Blocks the end-to-end demo"), "high": ("d93f0b", "Needed for pitch claims, not for the pipeline to run")}
HIGH = {"P1:validate", "P7:patrol", "P2:ingest/era5", "P2:ingest/osm", "P3:reference/piers"}
MILESTONE = {"P1:core": 1, "P1:sim/simulate": 1, "stubs": 1, "P2": 2, "P3": 2}  # prefix rules; default 3

# HARD = cannot start until done. SOFT = needs the upstream's real output; start on the simulator meanwhile.
HARD = {
    "P1:core/grid": ["P1:core/crs"], "P1:core/split": ["P1:core/time"], "P1:core/observed": ["P1:core/time"],
    "P1:core/schemas": ["P1:core/crs", "P1:core/grid", "P1:core/observed", "P1:core/time"],
    "P1:core/io": ["P1:core/schemas", "P1:core/config"],
    "P1:sim/simulate": ["P1:core/grid", "P1:core/observed", "P1:core/schemas", "P1:core/io", "P1:core/split"],
    "P1:validate": ["P1:sim/simulate", "P1:core/io"],
    "P2:ingest/run": [f"P2:ingest/{g}" for g in ("probe", "s1", "gfw", "era5", "osm", "static")],
    "P3:reference/masks": ["P3:reference/cells"], "P3:reference/piers": ["P3:reference/cells"],
    "P3:coverage": ["P3:reference/masks"],
    "P4:detect/cfar": ["P4:detect/scene"], "P4:detect/ghost": ["P4:detect/cfar"], "P4:detect/pboat": ["P4:detect/ghost"],
    "P4:detect/run": ["P4:detect/scene", "P4:detect/cfar", "P4:detect/ghost", "P4:detect/pboat"],
    "P4:match": ["P4:detect/run"], "P5:forecast": ["P5:aggregate"], "P6:fuse": ["P6:detectors"],
    "P7:dashboard": ["P7:export"],
}
for g in ("probe", "s1", "gfw", "era5", "osm", "static"):
    HARD.setdefault(f"P2:ingest/{g}", []).append("P2:ingest/cache")
SOFT = {
    "P3:reference/cells": ["P2:ingest/static", "P2:ingest/osm"],
    "P3:reference/masks": ["P2:ingest/static", "P2:ingest/s1"], "P3:reference/piers": ["P2:ingest/osm"],
    "P3:coverage": ["P2:ingest/era5", "P2:ingest/s1"],
    "P4:detect/scene": ["P2:ingest/s1", "P3:reference/masks"], "P4:detect/run": ["P3:coverage"],
    "P4:match": ["P2:ingest/gfw"],
    "P5:aggregate": ["P4:match", "P3:coverage", "P3:reference/cells"], "P5:forecast": ["P3:reference/cells"],
    "P6:detectors": ["P5:aggregate", "P5:forecast"], "P6:fuse": ["P3:reference/piers", "P4:match"],
    "P7:patrol": ["P6:fuse", "P3:reference/piers"], "P7:export": ["P6:fuse", "P5:forecast", "P3:coverage", "P1:validate"],
    "P7:dashboard": ["P6:fuse"], "P1:validate": ["P6:fuse"],
}


def parse(module: str) -> tuple[list[tuple[str, str]], str]:
    text = Path(f"docs/specs/{module}.md").read_text()
    block = re.search(r"```text\n(.*?)```", text, re.DOTALL)
    groups: list[tuple[str, list[str]]] = []
    for line in (block.group(1) if block else "").splitlines():
        m = GROUP.match(line)
        if m:
            groups.append((m.group(1).rstrip("/") or m.group(1), [line]))
        elif groups and line.strip():
            groups[-1][1].append(line)
    tests = re.search(r"### Tests \(done when\)\n(.*?)(\n### |\Z)", text, re.DOTALL)
    return [(g, "\n".join(body)) for g, body in groups], (tests.group(1).strip() if tests else "")


def build() -> dict[str, dict]:
    """key -> {title, spec, hard, soft, prio, ms, wave}"""
    items: dict[str, dict] = {}
    for n in range(1, 8):
        mod = f"P{n}"
        groups, tests = parse(mod)
        stub = f"{mod}:stubs"
        names = "\n".join(f"- `{g}`" for g, _ in groups)
        items[stub] = dict(
            title=f"[{mod}] Stubs for every public function",
            spec=f"Create every public function from the pseudo-codebase in `docs/specs/{mod}.md` as a stub returning "
                 f"schema-valid simulator output, so `make sim && make all` runs end to end on the simulator.\n\nGroups:\n{names}",
            hard=["P1:core/schemas", "P1:sim/simulate"] if n > 1 else ["P1:core/schemas"], soft=[])
        for g, body in groups:
            key = f"{mod}:{g}"
            items[key] = dict(
                title=f"[{mod}] Implement {g}",
                spec=f"Spec: `docs/specs/{mod}.md`, pseudo-codebase group `{g}`. Read the module's Steps, Warnings and the "
                     f"shared Review passes table first.\n\n```text\n{body}\n```\n\nDone when the `test:` lines above pass on the "
                     f"simulator, plus the relevant items from the module's Tests list:\n\n{tests}",
                hard=([stub] if n > 1 else []) + HARD.get(key, []), soft=SOFT.get(key, []))
    for k, it in items.items():
        it["hard"] = list(dict.fromkeys(it["hard"]))
        it["prio"] = "high" if k in HIGH else "critical"
        it["ms"] = next((v for pre, v in MILESTONE.items() if k.startswith(pre) or k.endswith(pre)), 3)
        if k.startswith("P1:validate"):
            it["ms"] = 3
    unknown = {d for it in items.values() for d in it["hard"] + it["soft"]} - items.keys()
    assert not unknown, unknown
    wave: dict[str, int] = {}

    def depth(k: str) -> int:
        if k not in wave:
            wave[k] = 1 + max([depth(d) for d in items[k]["hard"]], default=0)
        return wave[k]
    for k in items:
        items[k]["wave"] = depth(k)
    return items


def short(k: str) -> str:
    return k.replace(":", " ")


def mermaid(items: dict) -> str:
    nid = {k: f"n{i}" for i, k in enumerate(items)}
    lines = ["graph LR"] + [f'  {nid[k]}["{short(k)}"]' for k in items if not k.endswith(":stubs")]
    for k, it in items.items():
        if k.endswith(":stubs"):
            continue
        lines += [f"  {nid[d]} --> {nid[k]}" for d in it["hard"] if not d.endswith(":stubs")]
        lines += [f"  {nid[d]} -.-> {nid[k]}" for d in it["soft"]]
    return "```mermaid\n" + "\n".join(lines) + "\n```"


def plan_md(items: dict, num: dict[str, int] | None = None) -> str:
    ref = (lambda k: f"#{num[k]}") if num else (lambda k: f"`{short(k)}`")
    out = ["# Issue plan: build order, priority, dependencies\n",
           "**Solid arrow / Blocked by** = cannot start until done. **Dashed / Needs real output from** = start on the simulator, switch to real data when it lands.\n"]
    for w in sorted({i["wave"] for i in items.values()}):
        out.append(f"\n## Wave {w}\n")
        for k, it in items.items():
            if it["wave"] != w:
                continue
            tag = "🔴 critical" if it["prio"] == "critical" else "🟠 high"
            out.append(f"- {'[ ] ' if num else ''}**{ref(k)}** {it['title'].split('] ', 1)[1]} · {tag} · M{it['ms']}"
                       + (f"\n  - Blocked by: {', '.join(ref(d) for d in it['hard'])}" if it["hard"] else "")
                       + (f"\n  - Needs real output from: {', '.join(ref(d) for d in it['soft'])}" if it["soft"] else ""))
    return "\n".join(out) + "\n"


def api(method: str, path: str, data: dict | None = None) -> dict | list:
    r = subprocess.run(["gh", "api", "-X", method, path, "--input", "-"], input=json.dumps(data or {}),
                       capture_output=True, text=True, check=False)
    if r.returncode:
        raise RuntimeError(f"{method} {path}: {r.stdout} {r.stderr}")
    return json.loads(r.stdout or "null")


def apply(items: dict) -> None:
    for name, (color, desc) in PRIO.items():
        if subprocess.run(["gh", "api", f"repos/{{owner}}/{{repo}}/labels/priority:{name}"], capture_output=True, check=False).returncode:
            api("POST", "repos/{owner}/{repo}/labels", {"name": f"priority:{name}", "color": color, "description": desc})
    mids: dict[int, int] = {}
    have = {m["title"]: m["number"] for m in api("GET", "repos/{owner}/{repo}/milestones?state=all&per_page=100")}
    for i, title in M.items():
        mids[i] = have.get(title) or api("POST", "repos/{owner}/{repo}/milestones", {"title": title, "due_on": DUE[i]})["number"]
    existing = {i["title"]: i["number"] for i in api("GET", "repos/{owner}/{repo}/issues?state=all&per_page=100")}
    num: dict[str, int] = {}
    ids: dict[str, int] = {}
    full: dict[str, int] = {}

    def order(k: str) -> int:  # soft links count here, so a number exists before anything references it
        if k not in full:
            full[k] = 1 + max([order(d) for d in items[k]["hard"] + items[k]["soft"]], default=0)
        return full[k]
    for k in sorted(items, key=order):
        it = items[k]
        if it["title"] in existing:
            num[k] = existing[it["title"]]
            continue
        ref = lambda ks: ", ".join(f"#{num[d]}" for d in ks) or "nothing"
        body = (f"**Priority:** {it['prio']} · **Milestone:** {M[it['ms']]} · **Build wave:** {it['wave']}\n\n"
                f"**Blocked by (cannot start):** {ref(it['hard'])}\n"
                f"**Needs real output from (start on the simulator meanwhile):** {ref(it['soft'])}\n\n---\n\n{it['spec']}\n")
        mod = k.split(":")[0]
        r = api("POST", "repos/{owner}/{repo}/issues", {
            "title": it["title"], "body": body, "milestone": mids[it["ms"]],
            "labels": [f"module:{mod}", "task", f"priority:{it['prio']}"] + (["stub"] if k.endswith(":stubs") else [])})
        num[k], ids[k] = r["number"], r["id"]
        print(f"#{num[k]} {it['title']}")
    for k, it in items.items():  # native "blocked by" links, best effort
        for d in it["hard"]:
            if k in ids and d in ids:
                try:
                    api("POST", f"repos/{{owner}}/{{repo}}/issues/{num[k]}/dependencies/blocked_by", {"issue_id": ids[d]})
                except RuntimeError as e:
                    print("native dependency link failed (body text still lists them):", str(e)[:120])
                    break
    for k, it in items.items():  # second pass: add "Unblocks"
        if k not in ids:
            continue
        down = [n for n, o in items.items() if k in o["hard"] or k in o["soft"]]
        if down:
            b = api("GET", f"repos/{{owner}}/{{repo}}/issues/{num[k]}")["body"]
            api("PATCH", f"repos/{{owner}}/{{repo}}/issues/{num[k]}",
                {"body": b.replace("\n\n---\n\n", f"\n**Unblocks:** {', '.join(f'#{num[d]}' for d in down)}\n\n---\n\n", 1)})
    title = "[ALL] Build order and dependency map"
    if title not in existing:
        r = api("POST", "repos/{owner}/{repo}/issues", {"title": title, "labels": ["task"], "body":
                mermaid(items) + "\n\n" + plan_md(items, num)})
        print(f"#{r['number']} {title}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    items = build()
    Path("docs/issue-plan.md").write_text(plan_md(items) + "\n## Dependency graph\n\n" + mermaid(items) + "\n")
    print(plan_md(items))
    if a.apply:
        apply(items)
    else:
        print(f"{len(items) + 1} issues would be created (dry run; add --apply). Plan written to docs/issue-plan.md")


if __name__ == "__main__":
    main()
