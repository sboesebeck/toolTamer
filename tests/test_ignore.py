"""Tests for the ignore engine (tui/core/ignore.py).

These pin the gitignore semantics the whole feature rests on: anchors, `**`,
`!` negation, `dir/`, nested ignore files, and `.ttignore` winning over
`.gitignore`."""

from pathlib import Path

import pytest

from tui.core.ignore import IgnoreMatcher, append_ignore, iter_visible, load


def _tree(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("m\n")
    (root / "src" / "main.pyc").write_text("c\n")
    (root / "build").mkdir()
    (root / "build" / "out.o").write_text("o\n")
    (root / "secrets").mkdir()
    (root / "secrets" / "token.json").write_text("{}\n")


def test_load_is_none_without_ignore_files(tmp_path: Path):
    _tree(tmp_path)
    assert load(tmp_path) is None


def test_load_is_none_for_missing_directory(tmp_path: Path):
    assert load(tmp_path / "nope") is None


def test_load_finds_a_nested_ignore_file(tmp_path: Path):
    _tree(tmp_path)
    (tmp_path / "src" / ".gitignore").write_text("*.pyc\n")
    assert load(tmp_path) is not None


def test_anchor_matches_only_at_the_root(tmp_path: Path):
    _tree(tmp_path)
    (tmp_path / ".gitignore").write_text("/main.py\n")
    m = load(tmp_path)
    assert m is not None
    assert m.is_ignored("main.py")
    # /main.py is anchored; src/main.py must not match.
    assert not m.is_ignored("src/main.py")


def test_dir_pattern_prunes_the_directory_and_its_children(tmp_path: Path):
    _tree(tmp_path)
    (tmp_path / ".gitignore").write_text("build/\n")
    m = load(tmp_path)
    assert m is not None
    assert m.is_ignored("build", is_dir=True)
    assert m.is_ignored("build/out.o")
    assert not m.is_ignored("src/main.py")


def test_double_star_matches_across_directories(tmp_path: Path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "x.log").write_text("x\n")
    (tmp_path / "keep.log").write_text("k\n")
    (tmp_path / ".gitignore").write_text("**/x.log\n")
    m = load(tmp_path)
    assert m is not None
    assert m.is_ignored("a/b/x.log")
    assert not m.is_ignored("keep.log")


def test_negation_re_includes(tmp_path: Path):
    _tree(tmp_path)
    # `*.pyc` has no slash, so it matches at any depth; the negation then
    # brings src/main.pyc back.
    (tmp_path / ".gitignore").write_text("*.pyc\n!src/main.pyc\n")
    m = load(tmp_path)
    assert m is not None
    assert not m.is_ignored("src/main.pyc")
    assert m.is_ignored("main.pyc")


def test_cannot_re_include_under_an_excluded_directory(tmp_path: Path):
    """Git's rule: a file cannot come back once a parent directory is
    excluded. This is also what keeps a filter run over every file equal to
    the pruned walk."""
    _tree(tmp_path)
    (tmp_path / ".gitignore").write_text("build/\n")
    (tmp_path / "build" / ".gitignore").write_text("!out.o\n")
    m = load(tmp_path)
    assert m is not None
    assert m.is_ignored("build/out.o")


def test_nested_gitignore_is_scoped_to_its_directory(tmp_path: Path):
    _tree(tmp_path)
    (tmp_path / "src" / ".gitignore").write_text("*.pyc\n")
    m = load(tmp_path)
    assert m is not None
    assert m.is_ignored("src/main.pyc")
    (tmp_path / "main.pyc").write_text("c\n")
    assert not m.is_ignored("main.pyc")


def test_ttignore_can_re_include_what_gitignore_ignored(tmp_path: Path):
    _tree(tmp_path)
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    (tmp_path / ".ttignore").write_text("!src/main.pyc\n")
    m = load(tmp_path)
    assert m is not None
    assert m.is_ignored("main.pyc")
    assert not m.is_ignored("src/main.pyc")


def test_iter_visible_equals_a_filter_run_over_all_files(tmp_path: Path):
    _tree(tmp_path)
    (tmp_path / ".gitignore").write_text("build/\nsecrets/\n")
    (tmp_path / "src" / ".gitignore").write_text("*.pyc\n")
    m = load(tmp_path)
    assert m is not None
    all_files = [
        p.relative_to(tmp_path).as_posix()
        for p in sorted(tmp_path.rglob("*"))
        if p.is_file()
    ]
    filtered = [rel for rel in all_files if not m.is_ignored(rel)]
    walked = sorted(rel for rel, _ in iter_visible(tmp_path, m))
    assert filtered == walked


def test_iter_visible_prunes_an_ignored_unreadable_directory(tmp_path: Path):
    import os

    _tree(tmp_path)
    (tmp_path / ".gitignore").write_text("build/\n")
    os.chmod(tmp_path / "build", 0o000)
    try:
        m = load(tmp_path)
        assert m is not None
        rels = sorted(rel for rel, _ in iter_visible(tmp_path, m))
        assert "src/main.py" in rels
        assert not any(rel.startswith("build/") for rel in rels)
    finally:
        os.chmod(tmp_path / "build", 0o755)


def test_append_ignore_anchors_and_is_idempotent(tmp_path: Path):
    append_ignore(tmp_path, "secrets/token.json", is_dir=False)
    append_ignore(tmp_path, "secrets/token.json", is_dir=False)
    append_ignore(tmp_path, "build/cache", is_dir=True)
    lines = (tmp_path / ".ttignore").read_text().splitlines()
    assert lines == ["/secrets/token.json", "/build/cache/"]


def test_append_ignore_pattern_actually_ignores(tmp_path: Path):
    _tree(tmp_path)
    append_ignore(tmp_path, "secrets/token.json", is_dir=False)
    m = load(tmp_path)
    assert m is not None
    assert m.is_ignored("secrets/token.json")


def test_append_ignore_handles_missing_trailing_newline(tmp_path: Path):
    (tmp_path / ".ttignore").write_text("!keep")
    append_ignore(tmp_path, "x.tmp", is_dir=False)
    assert (tmp_path / ".ttignore").read_text() == "!keep\n/x.tmp\n"


def test_matcher_constructor_is_usable_directly(tmp_path: Path):
    _tree(tmp_path)
    (tmp_path / ".gitignore").write_text("build/\n")
    m = IgnoreMatcher(tmp_path)
    assert m.is_ignored("build/out.o")


def test_remove_ignore_is_the_inverse_of_append(tmp_path: Path):
    from tui.core.ignore import append_ignore, remove_ignore

    root = tmp_path / "tree"
    root.mkdir()
    append_ignore(root, "secret.json", is_dir=False)
    append_ignore(root, "keep.txt", is_dir=False)
    assert (root / ".ttignore").read_text().splitlines() == ["/secret.json", "/keep.txt"]

    remove_ignore(root, "secret.json", is_dir=False)
    assert (root / ".ttignore").read_text().splitlines() == ["/keep.txt"]
    # missing line / missing file are no-ops
    remove_ignore(root, "never-there", is_dir=False)
    remove_ignore(tmp_path / "nope", "x", is_dir=False)
