"""Tests for tui/core/diff_render.py — pure logic, no Textual involved."""

import os
import subprocess
from pathlib import Path

import pytest

from tui.core.diff_render import render_changed_diffs


def _pair(tmp_path: Path, rel: str, repo_content: str, sys_content: str) -> None:
    """Write `rel` under both a fresh repo/ and sys/ tree with different content."""
    repo_file = tmp_path / "repo" / rel
    sys_file = tmp_path / "sys" / rel
    repo_file.parent.mkdir(parents=True, exist_ok=True)
    sys_file.parent.mkdir(parents=True, exist_ok=True)
    repo_file.write_text(repo_content)
    sys_file.write_text(sys_content)


def test_single_changed_text_file_gets_diff_lines(tmp_path: Path):
    _pair(tmp_path, "bar.conf", "old_value=1\nfoo=bar\n", "old_value=2\nfoo=bar\n")

    result = render_changed_diffs(tmp_path / "repo", tmp_path / "sys", ["bar.conf"])

    assert len(result.files) == 1
    cf = result.files[0]
    assert cf.rel == "bar.conf"
    assert cf.diff_lines is not None
    assert any(line.startswith("-old_value=1") for line in cf.diff_lines)
    assert any(line.startswith("+old_value=2") for line in cf.diff_lines)
    assert result.truncated is False
    assert result.diff_unavailable is False


def test_more_than_ten_changed_files_only_first_ten_get_diffs(tmp_path: Path):
    changed = []
    for i in range(11):
        rel = f"f{i:02d}.txt"
        _pair(tmp_path, rel, f"old-{i}\n", f"new-{i}\n")
        changed.append(rel)

    result = render_changed_diffs(tmp_path / "repo", tmp_path / "sys", changed)

    assert len(result.files) == 11
    for cf in result.files[:10]:
        assert cf.diff_lines is not None
    last = result.files[10]
    assert last.rel == "f10.txt"
    assert last.diff_lines is None
    assert last.binary_line is None
    assert last.symlink_line is None
    assert last.error is None
    assert result.truncated is True
    assert result.diff_unavailable is False


def test_total_line_budget_truncates_mid_batch(tmp_path: Path):
    # Each file differs on every one of 150 lines, so its diff (capped at
    # max_lines_per_file=100) always hits the 100-line per-file cap.
    changed = []
    for i in range(4):
        rel = f"big{i}.txt"
        repo_content = "".join(f"repo-{i}-{n}\n" for n in range(150))
        sys_content = "".join(f"sys-{i}-{n}\n" for n in range(150))
        _pair(tmp_path, rel, repo_content, sys_content)
        changed.append(rel)

    result = render_changed_diffs(
        tmp_path / "repo", tmp_path / "sys", changed,
        max_diffs=10, max_total_lines=250, max_lines_per_file=100,
    )

    assert len(result.files) == 4
    # 100 + 100 = 200 lines after two files; third file gets only the
    # remaining 50-line budget; fourth gets nothing.
    assert result.files[0].diff_lines is not None and len(result.files[0].diff_lines) == 100
    assert result.files[1].diff_lines is not None and len(result.files[1].diff_lines) == 100
    assert result.files[2].diff_lines is not None and len(result.files[2].diff_lines) == 50
    assert result.files[3].diff_lines is None
    assert result.truncated is True


def test_binary_file_shows_binary_line_not_raw_bytes(tmp_path: Path):
    repo_file = tmp_path / "repo" / "logo.png"
    sys_file = tmp_path / "sys" / "logo.png"
    repo_file.parent.mkdir(parents=True)
    sys_file.parent.mkdir(parents=True)
    repo_file.write_bytes(b"\x89PNG\x00\x01\x02repo")
    sys_file.write_bytes(b"\x89PNG\x00\x01\x02system-differs")

    result = render_changed_diffs(tmp_path / "repo", tmp_path / "sys", ["logo.png"])

    cf = result.files[0]
    assert cf.diff_lines is None
    assert cf.binary_line is not None
    assert cf.binary_line.startswith("Binary files ")
    assert "\x00" not in cf.binary_line


def test_changed_symlink_is_never_diffed(tmp_path: Path, monkeypatch):
    repo_link = tmp_path / "repo" / "link"
    sys_link = tmp_path / "sys" / "link"
    repo_link.parent.mkdir(parents=True)
    sys_link.parent.mkdir(parents=True)
    os.symlink("../shared/a", repo_link)
    os.symlink("../shared/b", sys_link)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("diff must not be invoked for a changed symlink")

    monkeypatch.setattr(subprocess, "run", fail_if_called)

    result = render_changed_diffs(tmp_path / "repo", tmp_path / "sys", ["link"])

    cf = result.files[0]
    assert cf.diff_lines is None
    assert cf.symlink_line is not None
    assert "../shared/a" in cf.symlink_line
    assert "../shared/b" in cf.symlink_line


def test_one_unreadable_file_does_not_block_the_next(tmp_path: Path, monkeypatch):
    _pair(tmp_path, "bad.conf", "x\n", "y\n")
    _pair(tmp_path, "good.conf", "old\n", "new\n")
    real_run = subprocess.run

    def flaky_run(cmd, *args, **kwargs):
        if "bad.conf" in cmd[-1]:
            raise OSError("Permission denied")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", flaky_run)

    result = render_changed_diffs(
        tmp_path / "repo", tmp_path / "sys", ["bad.conf", "good.conf"],
    )

    bad, good = result.files
    assert bad.error is not None
    assert bad.diff_lines is None
    assert good.error is None
    assert good.diff_lines is not None
    assert any(line.startswith("+new") for line in good.diff_lines)


def test_diff_binary_missing_sets_flag_and_skips_remaining(tmp_path: Path, monkeypatch):
    _pair(tmp_path, "a.conf", "1\n", "2\n")
    _pair(tmp_path, "b.conf", "3\n", "4\n")

    def missing_diff(*args, **kwargs):
        raise FileNotFoundError("diff not on PATH")

    monkeypatch.setattr(subprocess, "run", missing_diff)

    result = render_changed_diffs(tmp_path / "repo", tmp_path / "sys", ["a.conf", "b.conf"])

    assert result.diff_unavailable is True
    for cf in result.files:
        assert cf.diff_lines is None
        assert cf.binary_line is None
        assert cf.symlink_line is None
        assert cf.error is None
    # Missing-binary is its own signal, not the generic diff-count cap.
    assert result.truncated is False
