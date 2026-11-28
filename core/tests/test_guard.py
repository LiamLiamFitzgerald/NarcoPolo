"""The guard hook (.claude/hooks/guard.py): the module comes from the branch (#182), scratchpad
writes are allowed for any module (#106), and the repo stays guarded."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.narco_module import current_module, module_from_branch

ROOT = Path(__file__).resolve().parents[2]
HOOK = str(ROOT / ".claude" / "hooks" / "guard.py")


def _repo(tmp_path: Path, branch: str) -> Path:
    """A throwaway repo on `branch` with the real owners.json, so tests don't depend on the
    branch the test run happens to be on."""
    repo = tmp_path / "repo"
    (repo / ".github").mkdir(parents=True)
    shutil.copy(ROOT / ".github" / "owners.json", repo / ".github" / "owners.json")
    subprocess.run(["git", "init", "-q", "-b", branch, str(repo)], check=True)
    ident = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(
        ["git", "-C", str(repo), *ident, "commit", "-q", "--allow-empty", "-m", "init"], check=True
    )
    return repo


def _guard(repo: Path, path: str, module: str = "", **env: str) -> subprocess.CompletedProcess:
    e = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo), "NARCO_MODULE": module, **env}
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": path}})
    return subprocess.run(
        [sys.executable, HOOK], check=False, input=payload, text=True, env=e, capture_output=True
    )


def test_the_branch_sets_the_module(tmp_path):
    repo = _repo(tmp_path, "mod/p4/1")
    assert _guard(repo, str(repo / "fuse" / "x.py")).returncode == 2
    assert _guard(repo, str(repo / "detect" / "x.py")).returncode == 0
    repo6 = _repo(tmp_path / "b", "mod/p6/1")
    assert _guard(repo6, str(repo6 / "fuse" / "x.py")).returncode == 0


def test_narco_module_must_match_the_branch(tmp_path):
    repo = _repo(tmp_path, "mod/p4/1")
    r = _guard(repo, str(repo / "detect" / "x.py"), "P3")
    assert r.returncode == 2 and "NARCO_MODULE=P3" in r.stderr and "P4" in r.stderr
    assert _guard(repo, str(repo / "detect" / "x.py"), " p4 ").returncode == 0  # case, spaces


def test_no_module_branch_and_no_env_blocks_repo_edits(tmp_path):
    repo = _repo(tmp_path, "main")
    assert _guard(repo, str(repo / "core" / "io.py")).returncode == 2
    assert _guard(repo, str(repo / "detect" / "x.py"), "P4").returncode == 0  # env still works


def test_session_scratchpad_is_writable_without_a_module(tmp_path):
    repo = _repo(tmp_path, "main")
    assert _guard(repo, "/tmp/claude-0/-home-user-NarcoPolo/abc/scratchpad/x.py").returncode == 0
    assert _guard(repo, "/tmp/claude-0/x/abc/scratchpad/sub/x.png", "P7").returncode == 0


def test_narco_scratch_is_writable(tmp_path):
    repo = _repo(tmp_path, "main")
    scratch = tmp_path / "s"
    assert _guard(repo, str(scratch / "a.txt"), NARCO_SCRATCH=str(scratch)).returncode == 0


def test_other_paths_outside_the_repo_stay_blocked(tmp_path):
    repo = _repo(tmp_path, "mod/p1/1")
    assert _guard(repo, "/tmp/elsewhere/x.py").returncode == 2
    assert _guard(repo, "/tmp/claude-0/proj/abc/notes/x.py").returncode == 2  # not a scratchpad
    assert _guard(repo, "/tmp/claude-0/scratchpad").returncode == 2  # the folder, not a file in it


def test_a_broken_guard_fails_closed(tmp_path):
    repo = _repo(tmp_path, "mod/p4/1")
    e = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo), "NARCO_MODULE": ""}
    r = subprocess.run(
        [sys.executable, HOOK], input="not json", text=True, env=e, capture_output=True, check=False
    )
    assert r.returncode == 2 and "guard error" in r.stderr


@pytest.mark.parametrize(
    ("branch", "module"),
    [
        ("mod/p4/12", "P4"),
        ("MOD/P7/x", "P7"),
        ("mod/p8/1", None),
        ("main", None),
        ("integration", None),
        ("feature/mod/p1/1", None),
    ],
)
def test_check_paths_and_commit_hook_agree_with_current_module(tmp_path, branch, module):
    repo = _repo(tmp_path, branch)
    assert module_from_branch(branch) == current_module(repo) == module
    # commit-msg hook: the same module ends up as the subject tag
    hook = ROOT / ".githooks" / "commit-msg"
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    msg = tmp_path / "msg"
    msg.write_text("add a thing\n")
    subprocess.run(["bash", str(hook), str(msg)], cwd=repo, check=True)
    first = msg.read_text().splitlines()[0]
    assert first == (f"[{module}] add a thing" if module else "add a thing")
    # check_paths.py: a module branch is checked as that module, any other is skipped
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_paths.py"), branch, "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert ("ownership check skipped" in out) == (module is None)
