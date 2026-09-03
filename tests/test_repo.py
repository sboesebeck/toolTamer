"""Tests for git-repo tracking (tui/core/repo.py)."""

from pathlib import Path

from tui.core.repo import MARKER_NAME, RepoSpec, read_marker, write_marker


def test_read_marker_returns_none_without_marker(tmp_path: Path):
    assert read_marker(tmp_path) is None


def test_read_marker_parses_keys(tmp_path: Path):
    (tmp_path / MARKER_NAME).write_text(
        "url    = git@github.com:me/nvim.git\n"
        "branch = main\n"
        "force  = true\n"
    )
    spec = read_marker(tmp_path)
    assert spec == RepoSpec(url="git@github.com:me/nvim.git", branch="main", force=True)


def test_read_marker_ignores_comments_blanks_and_unknown_keys(tmp_path: Path):
    (tmp_path / MARKER_NAME).write_text(
        "# a comment\n"
        "\n"
        "url = https://example.com/r.git   # trailing comment\n"
        "future_key = whatever\n"
    )
    spec = read_marker(tmp_path)
    assert spec == RepoSpec(url="https://example.com/r.git", branch=None, force=False)


def test_read_marker_without_url_yields_empty_url(tmp_path: Path):
    (tmp_path / MARKER_NAME).write_text("branch = main\n")
    spec = read_marker(tmp_path)
    assert spec is not None
    assert spec.url == ""


def test_write_marker_roundtrips(tmp_path: Path):
    spec = RepoSpec(url="git@github.com:me/r.git", branch="dev", force=True)
    write_marker(tmp_path, spec)
    assert read_marker(tmp_path) == spec


def test_write_marker_creates_directory(tmp_path: Path):
    target = tmp_path / "a" / "b"
    write_marker(target, RepoSpec(url="u"))
    assert (target / MARKER_NAME).is_file()


def test_write_marker_omits_optional_keys_when_unset(tmp_path: Path):
    write_marker(tmp_path, RepoSpec(url="u"))
    text = (tmp_path / MARKER_NAME).read_text()
    assert "branch" not in text
    assert "force" not in text


import subprocess

import pytest

from tui.core.repo import detect, git_available


def _run(cwd: Path, *args: str) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def origin_repo(tmp_path: Path) -> Path:
    """A bare-ish repo that serves as 'the remote' in tests."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _run(origin, "git", "init", "--quiet", "--bare", "--initial-branch=main")
    seed = tmp_path / "seed"
    seed.mkdir()
    _run(seed, "git", "init", "--quiet", "--initial-branch=main")
    _run(seed, "git", "config", "user.email", "t@example.com")
    _run(seed, "git", "config", "user.name", "Test")
    (seed / "README.md").write_text("one\n")
    _run(seed, "git", "add", "README.md")
    _run(seed, "git", "commit", "--quiet", "-m", "init")
    _run(seed, "git", "remote", "add", "origin", str(origin))
    _run(seed, "git", "push", "--quiet", "origin", "main")
    return origin


@pytest.fixture
def clone(tmp_path: Path, origin_repo: Path) -> Path:
    work = tmp_path / "work"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin_repo), str(work)],
        check=True, capture_output=True,
    )
    _run(work, "git", "config", "user.email", "t@example.com")
    _run(work, "git", "config", "user.name", "Test")
    return work


def test_git_is_available_in_the_test_environment():
    assert git_available() is True


def test_detect_returns_none_for_plain_directory(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert detect(plain) is None


def test_detect_returns_none_for_missing_path(tmp_path: Path):
    assert detect(tmp_path / "nope") is None


def test_detect_reads_origin_and_branch(clone: Path, origin_repo: Path):
    spec = detect(clone)
    assert spec is not None
    assert spec.url == str(origin_repo)
    assert spec.branch == "main"
    assert spec.force is False


def test_detect_returns_none_for_subdirectory_of_a_repo(clone: Path):
    sub = clone / "sub"
    sub.mkdir()
    assert detect(sub) is None


def test_detect_returns_none_when_repo_has_no_origin(tmp_path: Path):
    solo = tmp_path / "solo"
    solo.mkdir()
    _run(solo, "git", "init", "--quiet", "--initial-branch=main")
    assert detect(solo) is None
