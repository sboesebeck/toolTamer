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


# --- built-in .ttbak rule -------------------------------------------------
#
# The backups ToolTamer writes while updating a file (<path>.ttbak) must be
# invisible to every operation, with or without ignore files, and no rule may
# re-include them.


def test_load_stays_none_when_only_ttbak_is_present(tmp_path: Path):
    _tree(tmp_path)
    (tmp_path / "src" / "main.py.ttbak").write_text("old\n")
    assert load(tmp_path) is None  # a backup is not an ignore file


def test_ttbak_is_invisible_without_ignore_files(tmp_path: Path):
    _tree(tmp_path)
    (tmp_path / "main.py.ttbak").write_text("b\n")
    (tmp_path / "secrets" / "token.json.ttbak").write_text("b\n")
    rels = sorted(rel for rel, _ in iter_visible(tmp_path, None))
    assert rels == [
        "build/out.o",
        "secrets/token.json",
        "src/main.py",
        "src/main.pyc",
    ]


def test_ttbak_directory_is_pruned_without_ignore_files(tmp_path: Path):
    _tree(tmp_path)
    (tmp_path / "old.ttbak").mkdir()
    (tmp_path / "old.ttbak" / "deleted.txt").write_text("x\n")
    (tmp_path / "old.ttbak" / "sub").mkdir()
    (tmp_path / "old.ttbak" / "sub" / "y.txt").write_text("y\n")
    assert load(tmp_path) is None
    rels = sorted(rel for rel, _ in iter_visible(tmp_path, None))
    assert rels == [
        "build/out.o",
        "secrets/token.json",
        "src/main.py",
        "src/main.pyc",
    ]


def test_ttbak_is_ignored_flat_and_inside_a_backup_directory(tmp_path: Path):
    """A flat `filter` run in Bash sees only rel paths, not the pruned walk,
    so `is_ignored` must hide every component, not just the full basename."""
    _tree(tmp_path)
    m = load(tmp_path)  # None: no ignore files
    assert m is None
    # Direct checks are what the Bash filter calls through the CLI matcher;
    # with no ignore files load() is None, so the CLI's own ttbak guard in
    # tui/ttignore.py covers that path. With a matcher present the rule must
    # still fire:
    (tmp_path / ".gitignore").write_text("build/\n")
    m = load(tmp_path)
    assert m is not None
    assert m.is_ignored("main.py.ttbak")
    assert m.is_ignored("secrets/token.json.ttbak")
    assert m.is_ignored("old.ttbak/deleted.txt")  # ancestor component
    assert m.is_ignored("old.ttbak/sub/y.txt")


def test_ttbak_cannot_be_re_included(tmp_path: Path):
    _tree(tmp_path)
    (tmp_path / "keep.txt").write_text("k\n")
    (tmp_path / "keep.txt.ttbak").write_text("b\n")
    (tmp_path / ".gitignore").write_text("*.ttbak\n!keep.txt.ttbak\n")
    m = load(tmp_path)
    assert m is not None
    assert m.is_ignored("keep.txt.ttbak")  # `!` cannot resurrect a backup
    assert not m.is_ignored("keep.txt")


def test_iter_visible_with_matcher_drops_ttbak(tmp_path: Path):
    _tree(tmp_path)
    (tmp_path / "main.py.ttbak").write_text("b\n")
    (tmp_path / "old.ttbak").mkdir()
    (tmp_path / "old.ttbak" / "x.txt").write_text("x\n")
    (tmp_path / ".gitignore").write_text("build/\n")
    m = load(tmp_path)
    assert m is not None
    rels = sorted(rel for rel, _ in iter_visible(tmp_path, m))
    assert rels == [".gitignore", "secrets/token.json", "src/main.py", "src/main.pyc"]


def test_ttbak_symlink_is_invisible(tmp_path: Path):
    outer = tmp_path
    (outer / "target.txt").write_text("t\n")
    (outer / "tree").mkdir()
    (outer / "tree" / "link.ttbak").symlink_to(outer / "target.txt")
    (outer / "tree" / "real.txt").write_text("r\n")
    assert load(outer / "tree") is None
    rels = sorted(rel for rel, _ in iter_visible(outer / "tree", None))
    assert rels == ["real.txt"]
