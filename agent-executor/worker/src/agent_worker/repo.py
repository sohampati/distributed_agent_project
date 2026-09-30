from __future__ import annotations

import base64
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


class CloneError(Exception):
    pass


@dataclass(frozen=True)
class Workspace:
    root: Path       # per-task directory; delete it to clean up
    work_tree: Path  # the checked-out files; the only thing mounted into the sandbox
    git_dir: Path    # kept outside work_tree so the sandbox can't tamper with git config or hooks


def clone(url: str, dest_root: Path, token: str | None = None, timeout: float = 120) -> Workspace:
    """Shallow-clones ``url`` into ``dest_root``/repo, with git metadata in ``dest_root``/git.

    With --separate-git-dir, git would leave a ``.git`` pointer file in the work tree; it is removed so the
    sandbox sees plain files only. The worker addresses the repository with --git-dir/--work-tree instead.
    """
    ws = Workspace(root=dest_root, work_tree=dest_root / "repo", git_dir=dest_root / "git")
    dest_root.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", "--separate-git-dir", str(ws.git_dir), url, str(ws.work_tree)],
        env=_git_env(token), capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise CloneError(result.stderr.strip() or f"git clone exited with code {result.returncode}")
    (ws.work_tree / ".git").unlink(missing_ok=True)
    return ws


def diff(workspace: Workspace) -> str:
    """Everything the sandbox changed in the work tree (modified, new and deleted files) as a patch."""
    git = ["git", f"--git-dir={workspace.git_dir}", f"--work-tree={workspace.work_tree}"]
    # Ignore any hooks or fsmonitor config, belt and braces: the git dir was never exposed to the sandbox.
    hardened = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]
    subprocess.run([*git, *hardened, "add", "--all"], env=_git_env(None), check=True, capture_output=True)
    return subprocess.run(
        [*git, *hardened, "diff", "--cached", "--no-color", "--no-ext-diff"],
        env=_git_env(None), check=True, capture_output=True, text=True,
    ).stdout


def _git_env(token: str | None) -> dict[str, str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}  # fail instead of prompting for credentials
    if token:
        # Passed as config through the environment (git >= 2.31), so the token never appears in argv / ps.
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env |= {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
        }
    return env
