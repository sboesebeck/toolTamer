"""Tests for the store-git warning (untracked .gitignore in a tracked dir)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tui.core.config import TTConfig
from tui.core.store_check import store_ignored_files, store_ignored_in_dir


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def base(tmp_path: Path) -> Path:
    base = tmp_path / "tt"
    (base / "configs" / "common" / "files" / "app").mkdir(parents=True)
    (base / "configs" / "common" / "files.conf").write_text("app;.config/app\n")
    host = base / "configs" / "testhost"
    host.mkdir(parents=True)
    (host / "includes.conf").write_text("")
    (host / "files").mkdir()
    (base / "configs" / "common" / "files" / "app" / "kept.txt").write_text("k\n")
    _git(base, "init", "--quiet")
    return base


def _home(tmp_path: Path, gitignore: str | None = "node_modules\n") -> Path:
    home = tmp_path / "home"
    sys_dir = home / ".config" / "app"
    sys_dir.mkdir(parents=True)
    (sys_dir / "kept.txt").write_text("k\n")
    if gitignore is not None:
        (sys_dir / ".gitignore").write_text(gitignore)
    return home


def test_untracked_gitignore_is_reported(base: Path, tmp_path: Path):
    home = _home(tmp_path)
    (base / "configs" / "common" / "files" / "app" / ".gitignore").write_text(
        "node_modules\n"
    )  # present on disk but never committed
    cfg = TTConfig(base)
    assert store_ignored_in_dir(cfg, "common", "app", ".config/app", home) == [".gitignore"]
    assert store_ignored_files(cfg, "testhost", home) == [("common", "app", ".gitignore")]


def test_tracked_gitignore_is_not_reported(base: Path, tmp_path: Path):
    home = _home(tmp_path)
    gi = base / "configs" / "common" / "files" / "app" / ".gitignore"
    gi.write_text("node_modules\n")
    _git(base, "add", "-f", str(gi))
    cfg = TTConfig(base)
    assert store_ignored_in_dir(cfg, "common", "app", ".config/app", home) == []


def test_missing_gitignore_is_reported(base: Path, tmp_path: Path):
    home = _home(tmp_path)
    cfg = TTConfig(base)
    assert store_ignored_in_dir(cfg, "common", "app", ".config/app", home) == [".gitignore"]


def test_other_visible_files_are_not_reported(base: Path, tmp_path: Path):
    home = _home(tmp_path, gitignore=None)
    cfg = TTConfig(base)
    assert store_ignored_in_dir(cfg, "common", "app", ".config/app", home) == []
