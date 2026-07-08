# Copyright 2025-2026 Dimensional Inc.
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

"""``dimos deploy`` — dax-agent robot install git sync helpers."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from typing import Sequence

import typer

DEFAULT_INSTALL_DIR = Path("/opt/dax-agent")
DEFAULT_REMOTE_NAME = "origin"
DEFAULT_REMOTE_URL = "git@github.com:NIkok0/dimos.git"
DEFAULT_BRANCH = "deploy/dax-agent"
DEFAULT_SERVICE = "dax-agent"

app = typer.Typer(
    help="dax-agent robot deployment helpers (git sync on /opt/dax-agent)",
    no_args_is_help=True,
)


def _run_git(install_dir: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    if shutil.which("git") is None:
        typer.echo("Error: git not found in PATH", err=True)
        raise typer.Exit(1)
    typer.echo(f"  git {' '.join(args)}")
    return subprocess.run(
        ["git", *args],
        cwd=install_dir,
        check=check,
        text=True,
    )


def _remote_url(install_dir: Path, remote_name: str) -> str | None:
    result = subprocess.run(
        ["git", "remote", "get-url", remote_name],
        cwd=install_dir,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _ensure_remote(install_dir: Path, remote_name: str, remote_url: str) -> None:
    existing = _remote_url(install_dir, remote_name)
    if existing is None:
        _run_git(install_dir, "remote", "add", remote_name, remote_url)
        return
    if existing != remote_url:
        typer.echo(
            f"  remote {remote_name} already set to {existing!r}, leaving unchanged",
        )


def init_git_tree(
    install_dir: Path,
    *,
    remote_name: str = DEFAULT_REMOTE_NAME,
    remote_url: str = DEFAULT_REMOTE_URL,
    branch: str = DEFAULT_BRANCH,
) -> None:
    """Turn a rsync/copy install into a tracked git checkout."""
    if not install_dir.is_dir():
        raise FileNotFoundError(f"install dir not found: {install_dir}")

    if not (install_dir / ".git").exists():
        _run_git(install_dir, "init")

    _ensure_remote(install_dir, remote_name, remote_url)
    _run_git(install_dir, "fetch", remote_name, branch)
    _run_git(install_dir, "checkout", "-B", branch, f"{remote_name}/{branch}")


def pull_git_tree(
    install_dir: Path,
    *,
    remote_name: str = DEFAULT_REMOTE_NAME,
    branch: str = DEFAULT_BRANCH,
) -> None:
    """Fast-forward the install dir from its git remote."""
    if not (install_dir / ".git").is_dir():
        raise RuntimeError(
            f"{install_dir} is not a git repo — run: dimos deploy init-git --dir {install_dir}",
        )
    _run_git(install_dir, "pull", "--ff-only", remote_name, branch)


def restart_service(service: str, *, use_sudo: bool) -> None:
    cmd: Sequence[str]
    if use_sudo:
        cmd = ("sudo", "systemctl", "restart", service)
    else:
        cmd = ("systemctl", "--user", "restart", service) if os.geteuid() != 0 else (
            "systemctl",
            "restart",
            service,
        )
    typer.echo(f"  {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


@app.command("init-git")
def init_git_cmd(
    dir: Path = typer.Option(
        DEFAULT_INSTALL_DIR,
        "--dir",
        "-C",
        help="dax-agent install directory (default: /opt/dax-agent)",
    ),
    remote: str = typer.Option(
        DEFAULT_REMOTE_URL,
        "--remote",
        "-r",
        help="Git remote URL",
    ),
    remote_name: str = typer.Option(
        DEFAULT_REMOTE_NAME,
        "--remote-name",
        help="Git remote name",
    ),
    branch: str = typer.Option(
        DEFAULT_BRANCH,
        "--branch",
        "-b",
        help="Branch to track",
    ),
) -> None:
    """Initialize git in an existing install so ``dimos deploy pull`` works."""
    typer.echo(f"==> init-git in {dir}")
    try:
        init_git_tree(dir, remote_name=remote_name, remote_url=remote, branch=branch)
    except subprocess.CalledProcessError as exc:
        typer.echo(f"Error: git command failed (exit {exc.returncode})", err=True)
        raise typer.Exit(exc.returncode) from exc
    except FileNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo("==> Done. Update with: dimos deploy pull")


@app.command("pull")
def pull_cmd(
    dir: Path = typer.Option(
        DEFAULT_INSTALL_DIR,
        "--dir",
        "-C",
        help="dax-agent install directory",
    ),
    remote_name: str = typer.Option(
        DEFAULT_REMOTE_NAME,
        "--remote-name",
        help="Git remote name",
    ),
    branch: str = typer.Option(
        DEFAULT_BRANCH,
        "--branch",
        "-b",
        help="Branch to pull",
    ),
    restart: bool = typer.Option(
        False,
        "--restart",
        help="Restart systemd dax-agent after pull",
    ),
    service: str = typer.Option(
        DEFAULT_SERVICE,
        "--service",
        help="systemd unit name (without .service)",
    ),
    sudo: bool = typer.Option(
        False,
        "--sudo",
        help="Use sudo for systemctl restart",
    ),
) -> None:
    """Pull latest deploy/dax-agent code; optionally restart the service."""
    typer.echo(f"==> pull in {dir} ({remote_name}/{branch})")
    try:
        pull_git_tree(dir, remote_name=remote_name, branch=branch)
    except RuntimeError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    except subprocess.CalledProcessError as exc:
        typer.echo(f"Error: git pull failed (exit {exc.returncode})", err=True)
        raise typer.Exit(exc.returncode) from exc

    if restart:
        typer.echo(f"==> restart {service}")
        try:
            restart_service(service, use_sudo=sudo)
        except subprocess.CalledProcessError as exc:
            typer.echo(f"Error: systemctl failed (exit {exc.returncode})", err=True)
            raise typer.Exit(exc.returncode) from exc

    typer.echo("==> Done")
