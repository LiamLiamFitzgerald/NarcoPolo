"""The guard hook (.claude/hooks/guard.py): scratchpad writes are allowed for any module (#106); the repo stays guarded."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _guard(path: str, module: str = "", **env: str) -> int:
    e = {**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT), "NARCO_MODULE": module, **env}
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": path}})
    hook = str(ROOT / ".claude" / "hooks" / "guard.py")
    return subprocess.run(
        [sys.executable, hook], check=False, input=payload, text=True, env=e, capture_output=True
    ).returncode


def test_session_scratchpad_is_writable_without_a_module():
    assert _guard("/tmp/claude-0/-home-user-NarcoPolo/abc/scratchpad/x.py") == 0
    assert _guard("/tmp/claude-0/-home-user-NarcoPolo/abc/scratchpad/sub/x.png", "P7") == 0


def test_narco_scratch_is_writable(tmp_path):
    assert _guard(str(tmp_path / "a.txt"), NARCO_SCRATCH=str(tmp_path)) == 0


def test_other_paths_outside_the_repo_stay_blocked():
    assert _guard("/tmp/elsewhere/x.py", "P1") == 2
    assert _guard("/tmp/claude-0/proj/abc/notes/x.py", "P1") == 2  # not a scratchpad
    assert _guard("/tmp/claude-0/scratchpad", "P1") == 2  # the folder itself is not a file in it


def test_repo_files_still_follow_ownership():
    assert _guard(str(ROOT / "core" / "io.py"), "P4") == 2
    assert _guard(str(ROOT / "detect" / "x.py"), "P4") == 0
    assert _guard(str(ROOT / "core" / "io.py")) == 2  # no module: nothing in the repo
