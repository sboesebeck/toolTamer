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
