"""Tests for the machine-id override of the hostname."""

from pathlib import Path

from tui.core.machine_id import read_machine_id, write_machine_id


def test_missing_file_returns_none(tmp_path: Path):
    assert read_machine_id(tmp_path) is None


def test_empty_file_returns_none(tmp_path: Path):
    (tmp_path / "machine-id").write_text("")
    assert read_machine_id(tmp_path) is None


def test_whitespace_only_file_returns_none(tmp_path: Path):
    (tmp_path / "machine-id").write_text("  \n\t\n")
    assert read_machine_id(tmp_path) is None


def test_reads_name_without_trailing_newline(tmp_path: Path):
    (tmp_path / "machine-id").write_text("gandalf.home.local\n")
    assert read_machine_id(tmp_path) == "gandalf.home.local"


def test_strips_surrounding_whitespace(tmp_path: Path):
    (tmp_path / "machine-id").write_text("  gandalf.home.local \t\n")
    assert read_machine_id(tmp_path) == "gandalf.home.local"


def test_only_first_line_counts(tmp_path: Path):
    # A stray second line (e.g. a comment pasted in by hand) must not leak
    # into the config name.
    (tmp_path / "machine-id").write_text("gandalf.home.local\nsomething else\n")
    assert read_machine_id(tmp_path) == "gandalf.home.local"


# --- write_machine_id --------------------------------------------------
#
# Mirrors writeMachineId() in bin/include.sh (pinned by
# tests/test_bash_machine_id.py): the config dir is a git repo shared by
# all machines, so the id must be ignored there, added exactly once.


def test_write_creates_file_with_newline(tmp_path: Path):
    write_machine_id(tmp_path, "gandalf")
    assert (tmp_path / "machine-id").read_text() == "gandalf\n"
    assert read_machine_id(tmp_path) == "gandalf"


def test_write_adds_gitignore_entry_once_in_a_repo(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("cache/\n")
    write_machine_id(tmp_path, "a")
    write_machine_id(tmp_path, "b")
    lines = (tmp_path / ".gitignore").read_text().splitlines()
    assert lines.count("machine-id") == 1
    assert "cache/" in lines


def test_write_respects_existing_gitignore_entry(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("machine-id\n")
    write_machine_id(tmp_path, "a")
    assert (tmp_path / ".gitignore").read_text() == "machine-id\n"


def test_write_creates_gitignore_in_repo_without_one(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    write_machine_id(tmp_path, "a")
    assert "machine-id" in (tmp_path / ".gitignore").read_text().splitlines()


def test_write_does_not_conjure_gitignore_outside_a_repo(tmp_path: Path):
    write_machine_id(tmp_path, "a")
    assert not (tmp_path / ".gitignore").exists()
