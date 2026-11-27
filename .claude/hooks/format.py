#!/usr/bin/env python3
"""Claude Code PostToolUse hook: format an edited Python file with ruff. Never blocks."""

import json
import subprocess
import sys

try:
    data = json.load(sys.stdin)
    path = (data.get("tool_input") or {}).get("file_path", "")
    if path.endswith(".py"):
        subprocess.run(["uv", "run", "--quiet", "ruff", "format", "--quiet", path],
                       timeout=30, check=False, capture_output=True)
        subprocess.run(["uv", "run", "--quiet", "ruff", "check", "--fix", "--quiet", path],
                       timeout=30, check=False, capture_output=True)
except Exception:
    pass
sys.exit(0)
