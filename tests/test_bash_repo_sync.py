"""Tests for the bash side of git-repo tracking (bin/include.sh).

The bash sync has no other test coverage, and these functions run git
against the user's real repositories — so they get direct tests rather
than a Python re-implementation that merely claims to match.
"""

import subprocess
from pathlib import Path

import pytest

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
        # here so it cannot pollute captured stdout in every test below —
        # pytest's tmp_path fixture handles cleanup on its own.
        f'trap - EXIT QUIT TERM\n'
        f'export BASE="{tmp}/base/"\n'
        f'export TMP="{tt_tmp}"\n'
        f'export HOST="testhost"\n'
        f"{snippet}\n"
    )
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, cwd=str(tmp)
    )


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def origin_repo(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "--quiet", "--bare", "--initial-branch=main")
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "--quiet", "--initial-branch=main")
    _git(seed, "config", "user.email", "t@example.com")
    _git(seed, "config", "user.name", "Test")
    (seed / "README.md").write_text("one\n")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "--quiet", "-m", "init")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "--quiet", "origin", "main")
    return origin


def make_marker(store: Path, url: str, branch: str = "main", force: bool = False) -> None:
    store.mkdir(parents=True, exist_ok=True)
    lines = [f"url    = {url}", f"branch = {branch}"]
    if force:
        lines.append("force  = true")
    (store / ".ttgit").write_text("\n".join(lines) + "\n")


def test_is_repo_entry_true_with_marker(tmp_path: Path):
    store = tmp_path / "store"
    make_marker(store, "git@example.com:me/r.git")
    result = run_bash(f'isRepoEntry "{store}" && echo YES || echo NO', tmp_path)
    assert result.stdout.strip() == "YES"


def test_is_repo_entry_false_for_plain_directory(tmp_path: Path):
    store = tmp_path / "store"
    store.mkdir()
    (store / "some.conf").write_text("x\n")
    result = run_bash(f'isRepoEntry "{store}" && echo YES || echo NO', tmp_path)
    assert result.stdout.strip() == "NO"


def test_read_repo_spec_returns_values(tmp_path: Path):
    store = tmp_path / "store"
    make_marker(store, "git@example.com:me/r.git", branch="dev", force=True)
    assert run_bash(f'readRepoSpec "{store}" url', tmp_path).stdout.strip() \
        == "git@example.com:me/r.git"
    assert run_bash(f'readRepoSpec "{store}" branch', tmp_path).stdout.strip() == "dev"
    assert run_bash(f'readRepoSpec "{store}" force', tmp_path).stdout.strip() == "true"


def test_read_repo_spec_is_empty_for_unset_key(tmp_path: Path):
    store = tmp_path / "store"
    make_marker(store, "u")
    assert run_bash(f'readRepoSpec "{store}" force', tmp_path).stdout.strip() == ""


def test_read_repo_spec_ignores_comments(tmp_path: Path):
    store = tmp_path / "store"
    store.mkdir()
    (store / ".ttgit").write_text("# url = wrong\nurl = right   # trailing\n")
    assert run_bash(f'readRepoSpec "{store}" url', tmp_path).stdout.strip() == "right"


def test_bash_and_python_agree_on_the_same_marker(tmp_path: Path):
    """The two parsers must not drift — same file, same answers."""
    from tui.core.repo import read_marker

    store = tmp_path / "store"
    store.mkdir()
    (store / ".ttgit").write_text(
        "# comment\n\nurl = git@example.com:me/r.git  # trailing\n"
        "branch = dev\nforce = true\nunknown = ignored\n"
    )
    spec = read_marker(store)
    assert spec.url == run_bash(f'readRepoSpec "{store}" url', tmp_path).stdout.strip()
    assert spec.branch == run_bash(f'readRepoSpec "{store}" branch', tmp_path).stdout.strip()
    assert spec.force is (
        run_bash(f'readRepoSpec "{store}" force', tmp_path).stdout.strip() == "true"
    )


def test_tt_git_top_level_for_repo_root(tmp_path: Path, origin_repo: Path):
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "--quiet", str(origin_repo), str(work)],
                   check=True, capture_output=True)
    result = run_bash(f'ttGitTopLevel "{work}"', tmp_path)
    assert Path(result.stdout.strip()).resolve() == work.resolve()


def test_tt_git_top_level_empty_for_plain_directory(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    result = run_bash(f'ttGitTopLevel "{plain}"', tmp_path)
    assert result.stdout.strip() == ""




def _summary(tmp_path: Path) -> str:
    f = tmp_path / "tt-tmp" / "summary"
    return f.read_text() if f.exists() else ""


def test_sync_repo_clones_when_target_missing(tmp_path: Path, origin_repo: Path):
    store = tmp_path / "store"
    make_marker(store, str(origin_repo))
    target = tmp_path / "sys" / "nvim"

    run_bash(f'syncRepoToSystem "{store}" "{target}"', tmp_path)

    assert (target / "README.md").read_text() == "one\n"
    assert "Cloned repo" in _summary(tmp_path)


def test_sync_repo_backs_up_non_repo_then_clones(tmp_path: Path, origin_repo: Path):
    store = tmp_path / "store"
    make_marker(store, str(origin_repo))
    target = tmp_path / "sys" / "nvim"
    target.mkdir(parents=True)
    (target / "old.txt").write_text("old\n")

    run_bash(f'syncRepoToSystem "{store}" "{target}"', tmp_path)

    assert (target / "README.md").is_file()
    assert (tmp_path / "sys" / "nvim.ttbak" / "old.txt").read_text() == "old\n"


def test_sync_repo_pulls_when_behind(tmp_path: Path, origin_repo: Path):
    store = tmp_path / "store"
    make_marker(store, str(origin_repo))
    target = tmp_path / "sys" / "nvim"
    subprocess.run(["git", "clone", "--quiet", str(origin_repo), str(target)],
                   check=True, capture_output=True)

    other = tmp_path / "other"
    subprocess.run(["git", "clone", "--quiet", str(origin_repo), str(other)],
                   check=True, capture_output=True)
    _git(other, "config", "user.email", "t@example.com")
    _git(other, "config", "user.name", "Test")
    (other / "remote.txt").write_text("remote\n")
    _git(other, "add", "remote.txt")
    _git(other, "commit", "--quiet", "-m", "remote")
    _git(other, "push", "--quiet", "origin", "main")

    run_bash(f'syncRepoToSystem "{store}" "{target}"', tmp_path)

    assert (target / "remote.txt").is_file()
    assert "Updated repo" in _summary(tmp_path)


def test_sync_repo_skips_dirty_worktree(tmp_path: Path, origin_repo: Path):
    store = tmp_path / "store"
    make_marker(store, str(origin_repo))
    target = tmp_path / "sys" / "nvim"
    subprocess.run(["git", "clone", "--quiet", str(origin_repo), str(target)],
                   check=True, capture_output=True)
    (target / "README.md").write_text("my work\n")

    run_bash(f'syncRepoToSystem "{store}" "{target}"', tmp_path)

    assert (target / "README.md").read_text() == "my work\n"
    assert "Skipped repo" in _summary(tmp_path)


def test_sync_repo_resets_dirty_worktree_with_force(tmp_path: Path, origin_repo: Path):
    store = tmp_path / "store"
    make_marker(store, str(origin_repo), force=True)
    target = tmp_path / "sys" / "nvim"
    subprocess.run(["git", "clone", "--quiet", str(origin_repo), str(target)],
                   check=True, capture_output=True)
    (target / "README.md").write_text("my work\n")
    (target / "junk.txt").write_text("junk\n")

    run_bash(f'syncRepoToSystem "{store}" "{target}"', tmp_path)

    assert (target / "README.md").read_text() == "one\n"
    assert not (target / "junk.txt").exists()
    assert "Reset repo" in _summary(tmp_path)


def test_sync_repo_skips_on_origin_mismatch(tmp_path: Path, origin_repo: Path):
    store = tmp_path / "store"
    make_marker(store, "git@example.com:someone/else.git")
    target = tmp_path / "sys" / "nvim"
    subprocess.run(["git", "clone", "--quiet", str(origin_repo), str(target)],
                   check=True, capture_output=True)

    run_bash(f'syncRepoToSystem "{store}" "{target}"', tmp_path)

    assert "origin" in _summary(tmp_path)
    assert (target / "README.md").read_text() == "one\n"


def test_sync_repo_reports_marker_without_url(tmp_path: Path):
    store = tmp_path / "store"
    store.mkdir()
    (store / ".ttgit").write_text("branch = main\n")
    target = tmp_path / "sys" / "nvim"

    run_bash(f'syncRepoToSystem "{store}" "{target}"', tmp_path)

    assert "Broken repo entry" in _summary(tmp_path)
    assert not target.exists()


def test_sync_file_routes_repo_entries_away_from_mirror(tmp_path: Path, origin_repo: Path):
    """syncFile must not call syncDirToSystem for a repo entry."""
    store = tmp_path / "store"
    make_marker(store, str(origin_repo))
    target = tmp_path / "sys" / "nvim"

    tt = REPO_ROOT / "bin" / "tt"
    tt_tmp = tmp_path / "tt-tmp"
    tt_tmp.mkdir(parents=True, exist_ok=True)

    lines = tt.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("function syncFile()"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}")
    sync_file_src = "\n".join(lines[start:end + 1]) + "\n"
    sync_file_path = tmp_path / "sync_file.sh"
    sync_file_path.write_text(sync_file_src)

    script = (
        f'source "{INCLUDE_SH}" >/dev/null 2>&1\n'
        f'trap - EXIT QUIT TERM\n'
        f'export BASE="{tmp_path}/base/"\n'
        f'export TMP="{tt_tmp}"\n'
        f'export HOST="testhost"\n'
        f'source "{sync_file_path}"\n'
        f'syncFile "{target}" "{store}"\n'
    )
    subprocess.run(["bash", "-c", script], capture_output=True, text=True)

    assert (target / "README.md").is_file()
    assert (target / ".git").exists()
