"""Tests for directory tracking: tree comparison, add_path coverage and
absorption of redundant entries."""

from pathlib import Path

import pytest

from tui.core.config import TTConfig, dir_diff, tree_hash


@pytest.fixture
def fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / ".config" / "wezterm" / "commands").mkdir(parents=True)
    (home / ".config" / "wezterm" / "wezterm.lua").write_text("return {}\n")
    (home / ".config" / "wezterm" / "commands" / "init.lua").write_text("-- init\n")
    (home / ".zshrc").write_text("# zshrc\n")
    return home


def test_mapping_line_without_semicolon_matches_bash(tmp_config: Path):
    """bash's `cut -f2 -d\\;` returns the whole line when there is no
    delimiter, so `bin/emate` syncs as stored=target — Python must agree."""
    macosx = tmp_config / "configs" / "macosx"
    (macosx / "files.conf").write_text("bin/emate\n;broken\n")
    cfg = TTConfig(tmp_config)
    assert cfg.get_file_mappings("macosx") == [("bin/emate", "bin/emate")]


def test_tree_hash_and_dir_diff(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    (a / "sub").mkdir(parents=True)
    b.mkdir()
    (a / "same.txt").write_text("x")
    (b / "same.txt").write_text("x")
    (a / "sub" / "only_a.txt").write_text("a")
    (b / "only_b.txt").write_text("b")
    (a / "changed.txt").write_text("1")
    (b / "changed.txt").write_text("2")

    assert tree_hash(a) != tree_hash(b)
    only_a, only_b, changed = dir_diff(a, b)
    assert only_a == ["sub/only_a.txt"]
    assert only_b == ["only_b.txt"]
    assert changed == ["changed.txt"]

    # After mirroring both sides equal
    (b / "sub").mkdir()
    (b / "sub" / "only_a.txt").write_text("a")
    (b / "only_b.txt").unlink()
    (b / "changed.txt").write_text("1")
    assert tree_hash(a) == tree_hash(b)
    assert dir_diff(a, b) == ([], [], [])


def test_add_dir_absorbs_nested_entries(tmp_config: Path, fake_home: Path):
    cfg = TTConfig(tmp_config)
    macosx = tmp_config / "configs" / "macosx"
    files = macosx / "files"
    # old-style entry stored outside the future dir snapshot
    (files / "wezterm").mkdir(parents=True)
    (files / "wezterm" / "wezterm.lua").write_text("old copy\n")
    (macosx / "files.conf").write_text(
        "aerospace.toml;.aerospace.toml\n"
        "wezterm/wezterm.lua;.config/wezterm/\n"
    )

    report = cfg.add_path("macosx", fake_home / ".config" / "wezterm", "testhost", home=fake_home)

    mappings = cfg.get_file_mappings("macosx")
    assert (".config/wezterm", ".config/wezterm") in mappings
    assert ("wezterm/wezterm.lua", ".config/wezterm/") not in mappings
    assert ("aerospace.toml", ".aerospace.toml") in mappings
    # snapshot complete, stale stored copy gone
    assert (files / ".config" / "wezterm" / "commands" / "init.lua").is_file()
    assert not (files / "wezterm").exists()
    assert any("Absorbed" in line for line in report)


def test_add_file_covered_by_tracked_dir_adds_no_entry(tmp_config: Path, fake_home: Path):
    cfg = TTConfig(tmp_config)
    cfg.add_path("macosx", fake_home / ".config" / "wezterm", "testhost", home=fake_home)

    # change the file on the "system", then try to add it
    sys_file = fake_home / ".config" / "wezterm" / "wezterm.lua"
    sys_file.write_text("return { changed = true }\n")
    before = cfg.get_file_mappings("macosx")
    report = cfg.add_path("testhost", sys_file, "testhost", home=fake_home)

    # no new mapping anywhere, but the snapshot copy got refreshed
    assert cfg.get_file_mappings("macosx") == before
    assert cfg.get_file_mappings("testhost") == [("kitty.conf", ".config/kitty/kitty.conf")]
    snap = tmp_config / "configs" / "macosx" / "files" / ".config" / "wezterm" / "wezterm.lua"
    assert snap.read_text() == "return { changed = true }\n"
    assert any("no new entry" in line for line in report)


def test_absorb_redundant_entries_cleans_wezterm_style_mess(tmp_config: Path, fake_home: Path):
    """Mimics the real macosx config: dir entry + old-style copies + flat
    entries inside the snapshot + a nested tracked dir."""
    cfg = TTConfig(tmp_config)
    macosx = tmp_config / "configs" / "macosx"
    files = macosx / "files"

    # snapshot of the whole dir (as created by add_path/copytree)
    snap = files / ".config" / "wezterm"
    (snap / "commands").mkdir(parents=True)
    (snap / "backgrounds").mkdir()
    (snap / "wezterm.lua").write_text("return {}\n")
    (snap / "commands" / "init.lua").write_text("-- init\n")
    (snap / "backgrounds" / "bg.png").write_text("png\n")
    # old-style separate copies
    (files / "wezterm").mkdir()
    (files / "wezterm" / "wezterm.lua").write_text("old\n")
    (files / "wezterm" / "orphan.lua").write_text("never referenced\n")

    (macosx / "files.conf").write_text(
        "aerospace.toml;.aerospace.toml\n"
        "wezterm/wezterm.lua;.config/wezterm/\n"
        ".config/wezterm/commands/init.lua;.config/wezterm/commands/init.lua\n"
        ".config/wezterm/backgrounds;.config/wezterm/backgrounds\n"
        ".config/wezterm;.config/wezterm\n"
        ";.vimrc\n"
    )

    report = cfg.absorb_redundant_entries("macosx", delete_orphans=True)

    mappings = cfg.get_file_mappings("macosx")
    assert mappings == [
        ("aerospace.toml", ".aerospace.toml"),
        (".config/wezterm", ".config/wezterm"),
    ]
    # stale old-style copy deleted, orphan deleted, snapshot untouched
    assert not (files / "wezterm").exists()
    assert (snap / "commands" / "init.lua").is_file()
    assert (snap / "backgrounds" / "bg.png").is_file()
    assert any("broken entry" in line for line in report)


def test_absorb_keeps_unrelated_entries_and_files(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    macosx = tmp_config / "configs" / "macosx"
    files = macosx / "files"
    (files / ".config" / "nvim").mkdir(parents=True)
    (files / ".config" / "nvim" / "init.vim").write_text("set nu\n")
    (files / "aerospace.toml").write_text("[binding]\n")
    (macosx / "files.conf").write_text(
        "aerospace.toml;.aerospace.toml\n"
        ".config/nvim;.config/nvim\n"
    )
    report = cfg.absorb_redundant_entries("macosx", delete_orphans=True)
    assert cfg.get_file_mappings("macosx") == [
        ("aerospace.toml", ".aerospace.toml"),
        (".config/nvim", ".config/nvim"),
    ]
    assert (files / "aerospace.toml").is_file()
    assert (files / ".config" / "nvim" / "init.vim").is_file()
    assert report == [] or all("Absorbed" not in line for line in report)
