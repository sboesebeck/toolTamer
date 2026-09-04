"""Tests for the machine-id override of the hostname."""

from pathlib import Path

from tui.core.machine_id import read_machine_id


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
