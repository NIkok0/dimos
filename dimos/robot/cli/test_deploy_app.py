# Copyright 2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pathlib import Path
import subprocess

import pytest

from dimos.robot.cli.deploy_app import init_git_tree, pull_git_tree


@pytest.fixture
def bare_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Bare remote + empty install dir (simulates rsync'd robot tree)."""
    remote = tmp_path / "remote.git"
    install = tmp_path / "dax-agent"
    install.mkdir()
    (install / "README.md").write_text("robot copy\n")

    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=work, check=True)
    (work / "deploy.txt").write_text("v1\n")
    subprocess.run(["git", "add", "deploy.txt"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "deploy/dax-agent"], cwd=work, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=work, check=True)
    subprocess.run(["git", "push", "-u", "origin", "deploy/dax-agent"], cwd=work, check=True)

    return remote, install


def test_init_git_tree_tracks_remote_branch(bare_repo: tuple[Path, Path]) -> None:
    remote, install = bare_repo
    init_git_tree(
        install,
        remote_name="origin",
        remote_url=str(remote),
        branch="deploy/dax-agent",
    )
    assert (install / ".git").is_dir()
    assert (install / "deploy.txt").read_text() == "v1\n"


def test_pull_git_tree_fast_forwards(bare_repo: tuple[Path, Path]) -> None:
    remote, install = bare_repo
    init_git_tree(install, remote_url=str(remote), branch="deploy/dax-agent")

    work = install.parent / "work2"
    subprocess.run(["git", "clone", str(remote), str(work)], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "deploy/dax-agent"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=work, check=True)
    (work / "deploy.txt").write_text("v2\n")
    subprocess.run(["git", "add", "deploy.txt"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "v2"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "push"], cwd=work, check=True, capture_output=True)

    pull_git_tree(install, branch="deploy/dax-agent")
    assert (install / "deploy.txt").read_text() == "v2\n"


def test_pull_git_tree_requires_git_repo(tmp_path: Path) -> None:
    install = tmp_path / "dax-agent"
    install.mkdir()
    with pytest.raises(RuntimeError, match="not a git repo"):
        pull_git_tree(install)
