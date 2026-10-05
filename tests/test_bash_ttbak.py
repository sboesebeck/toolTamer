"""Bash-side tests for the built-in .ttbak backup rule (bin/include.sh).

The backups ToolTamer writes while updating a file (`<path>.ttbak`) are
invisible to every directory operation: hashing, extra detection, and the
mirror in both directions. The Python ignore engine (tui/core/ignore.py)
covers the TUI and the ignore-aware mirror; these tests pin the plain-find
and rsync paths that run when a tree has no ignore files.
"""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INCLUDE_SH = REPO_ROOT / "bin" / "include.sh"


def run_bash(snippet: str, tmp: Path) -> subprocess.CompletedProcess:
    """Source include.sh, then run `snippet`.

    BASE/TMP/HOST are overridden *after* sourcing because include.sh
    exports BASE=$HOME/.config/toolTamer at source time."""
    tt_tmp = tmp / "tt-tmp"
    tt_tmp.mkdir(parents=True, exist_ok=True)
    script = (
        f'source "{INCLUDE_SH}" >/dev/null 2>&1\n'
        # include.sh installs `trap cleanup EXIT ...` at source time, and
        # cleanup unconditionally echoes "Cleaning up" to stdout. Cancel it
        # here so it cannot pollute captured stdout.
        f'trap - EXIT QUIT TERM\n'
        f'export BASE="{tmp}/base/"\n'
        f'export TMP="{tt_tmp}"\n'
        f'export HOST="testhost"\n'
        f"{snippet}\n"
    )
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, cwd=str(tmp)
    )


def test_treehash_is_unchanged_by_ttbak_files_and_dirs(tmp_path: Path):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "keep.txt").write_text("keep\n")
    before = run_bash(f'treeHash "{tree}"', tmp_path).stdout.strip()

    (tree / "keep.txt.ttbak").write_text("old\n")
    (tree / "archive.ttbak").mkdir()
    (tree / "archive.ttbak" / "x.txt").write_text("x\n")
    (tree / "sub").mkdir()
    (tree / "sub" / "y.ttbak").write_text("y\n")

    after = run_bash(f'treeHash "{tree}"', tmp_path).stdout.strip()
    assert before != "missing"
    assert before == after


def test_listdirextras_does_not_report_ttbak(tmp_path: Path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "keep.txt").write_text("keep\n")
    (dst / "keep.txt").write_text("keep\n")
    (dst / "keep.txt.ttbak").write_text("old\n")
    (dst / "archive.ttbak").mkdir()
    (dst / "archive.ttbak" / "x").write_text("x\n")

    out = run_bash(f'listDirExtras "{src}" "{dst}"', tmp_path).stdout.strip()
    assert out == ""


def test_mirrordir_skips_ttbak_with_rsync(tmp_path: Path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    (src / "keep.txt").write_text("keep\n")
    (src / "old.ttbak").write_text("backup\n")
    (src / "sub").mkdir()
    (src / "sub" / "real.txt").write_text("real\n")
    (src / "sub" / "nested.ttbak").write_text("nested\n")
    (src / "dir.ttbak").mkdir()
    (src / "dir.ttbak" / "x.txt").write_text("x\n")

    r = run_bash(f'mirrorDir "{src}" "{dst}"', tmp_path)
    assert r.returncode == 0, r.stderr
    assert (dst / "keep.txt").is_file()
    assert (dst / "sub" / "real.txt").is_file()
    assert not (dst / "old.ttbak").exists()
    assert not (dst / "sub" / "nested.ttbak").exists()
    assert not (dst / "dir.ttbak").exists()


def test_find_expression_prunes_ttbak(tmp_path: Path):
    """Pin the exact `find` expression the no-ignore mirror branches use, so
    a platform without rsync still cannot see backups."""
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "keep.txt").write_text("keep\n")
    (tree / "backup.ttbak").write_text("b\n")
    (tree / "old.ttbak").mkdir()
    (tree / "old.ttbak" / "x.txt").write_text("x\n")
    (tree / "sub").mkdir()
    (tree / "sub" / "y.ttbak").write_text("y\n")

    snippet = (
        f'(cd "{tree}" && find . \\( -name \'*.ttbak\' -prune \\) '
        f'-o \\( -type f -o -type l \\) -print 2>/dev/null '
        f"| sed 's|^\\./||' | sort)"
    )
    out = run_bash(snippet, tmp_path).stdout.splitlines()
    assert out == ["keep.txt"]


def test_mirrordir_leaves_ttbak_backups_alone_on_the_destination(tmp_path: Path):
    """The backup survives on the destination (that is what a backup is for)
    but stays invisible: the mirror is a no-op, and the next sync still sees
    'Ok' instead of 'not in sync'."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    (src / "keep.txt").write_text("keep\n")

    first = run_bash(f"mirrorDir {src!s} {dst!s}", tmp_path)
    assert first.returncode == 0, first.stderr
    # Simulate the backup ToolTamer itself wrote next to a synced file.
    (dst / "keep.txt.ttbak").write_text("old\n")
    before = run_bash(f'treeHash "{src}"', tmp_path).stdout.strip()

    second = run_bash(f"mirrorDir {src!s} {dst!s}", tmp_path)
    assert second.returncode == 0, second.stderr
    assert (dst / "keep.txt").read_text() == "keep\n"
    # The backup is still there (never deleted), but invisible: the visible
    # sets of both sides still match, so no sync would be triggered.
    assert (dst / "keep.txt.ttbak").exists()
    assert run_bash(f'treeHash "{dst}"', tmp_path).stdout.strip() == before