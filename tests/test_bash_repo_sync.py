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


def test_is_repo_entry_true_when_marker_is_a_directory(tmp_path: Path):
    """isRepoEntry must fail CLOSED: anything at the marker path — even a
    directory, which [ -f ] alone would call "not a repo entry" — counts,
    so a corrupted marker is reported as broken rather than mirrored."""
    store = tmp_path / "store"
    (store / ".ttgit").mkdir(parents=True)
    result = run_bash(f'isRepoEntry "{store}" && echo YES || echo NO', tmp_path)
    assert result.stdout.strip() == "YES"


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


def test_bash_and_python_agree_on_duplicate_keys(tmp_path: Path):
    """A repeated key must resolve the same way in both parsers: LAST
    occurrence wins, matching tui/core/repo.py's read_marker (a dict built
    by iterating lines, so a later assignment overwrites an earlier one).

    This is the realistic "I appended force = false to turn force off"
    marker. If bash took the first occurrence instead, it would still see
    force = true and run `git reset --hard` while the TUI shows force off
    — the exact divergence this feature exists to prevent."""
    from tui.core.repo import read_marker

    store = tmp_path / "store"
    store.mkdir()
    (store / ".ttgit").write_text(
        "url    = git@example.com:me/a.git\n"
        "branch = dev\n"
        "force  = true\n"
        "url    = git@example.com:me/b.git\n"
        "branch = main\n"
        "force  = false\n"
    )
    spec = read_marker(store)
    assert spec.url == "git@example.com:me/b.git"
    assert spec.branch == "main"
    assert spec.force is False

    assert run_bash(f'readRepoSpec "{store}" url', tmp_path).stdout.strip() == spec.url
    assert run_bash(f'readRepoSpec "{store}" branch', tmp_path).stdout.strip() == spec.branch
    assert run_bash(f'readRepoSpec "{store}" force', tmp_path).stdout.strip() == "false"


def test_bash_and_python_agree_on_case_insensitive_force(tmp_path: Path):
    """force = TRUE (any case) must be treated as true by both sides —
    Python via .lower() == "true" in read_marker, bash via the tr-based
    fold in syncRepoToSystem. Pinning it here at the raw-value level:
    both parsers must at least extract the same raw string so the fold
    downstream operates on identical input."""
    from tui.core.repo import read_marker

    store = tmp_path / "store"
    store.mkdir()
    (store / ".ttgit").write_text("url    = git@example.com:me/r.git\nforce  = TRUE\n")
    spec = read_marker(store)
    assert spec.force is True

    raw = run_bash(f'readRepoSpec "{store}" force', tmp_path).stdout.strip()
    assert raw == "TRUE"
    assert (raw.lower() == "true") is spec.force


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


def test_sync_repo_resets_dirty_worktree_with_uppercase_force(tmp_path: Path, origin_repo: Path):
    """force = TRUE must reset just like force = true (Important 3: bash
    must fold case the same way tui/core/repo.py's spec.force does)."""
    store = tmp_path / "store"
    store.mkdir(parents=True)
    (store / ".ttgit").write_text(f"url    = {origin_repo}\nbranch = main\nforce  = TRUE\n")
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


def test_sync_repo_clone_failure_after_backup_leaves_backup_intact(tmp_path: Path):
    """Highest-blast-radius transition: target exists, is not a repo, gets
    moved to .ttbak, and the clone then fails (bad URL here — offline and
    deterministic). The original content must survive under .ttbak and the
    summary must name that backup so the user can find it."""
    store = tmp_path / "store"
    make_marker(store, str(tmp_path / "does-not-exist.git"))
    target = tmp_path / "sys" / "nvim"
    target.mkdir(parents=True)
    (target / "mine.txt").write_text("my original content\n")

    run_bash(f'syncRepoToSystem "{store}" "{target}"', tmp_path)

    assert not target.exists()
    backup = tmp_path / "sys" / "nvim.ttbak"
    assert (backup / "mine.txt").read_text() == "my original content\n"
    summary = _summary(tmp_path)
    assert "nvim.ttbak" in summary


def _run_sync_file(target: Path, store: Path, tmp_path: Path) -> subprocess.CompletedProcess:
    """Slice syncFile out of bin/tt (Ruling R6) and run it against a real
    target/store pair, with include.sh sourced first."""
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
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


def test_sync_file_routes_repo_entries_away_from_mirror(tmp_path: Path, origin_repo: Path):
    """syncFile must not call syncDirToSystem for a repo entry."""
    store = tmp_path / "store"
    make_marker(store, str(origin_repo))
    target = tmp_path / "sys" / "nvim"

    _run_sync_file(target, store, tmp_path)

    assert (target / "README.md").is_file()
    assert (target / ".git").exists()


def test_sync_file_survives_when_ttgit_marker_is_a_directory(tmp_path: Path, origin_repo: Path):
    """Regression: isRepoEntry must fail CLOSED. If `.ttgit` is itself a
    directory rather than a regular file, isRepoEntry must still report
    "this is a repo entry" so syncFile routes to syncRepoToSystem (which
    reports a broken marker and touches nothing) instead of falling
    through to syncDirToSystem -> mirrorDir, which would delete every
    file on the system side that isn't in the (near-empty) store."""
    store = tmp_path / "store"
    store.mkdir(parents=True)
    (store / ".ttgit").mkdir()  # marker path exists but is a directory

    target = tmp_path / "sys" / "nvim"
    subprocess.run(["git", "clone", "--quiet", str(origin_repo), str(target)],
                   check=True, capture_output=True)
    (target / "mine.txt").write_text("my work\n")

    _run_sync_file(target, store, tmp_path)

    assert (target / "README.md").is_file()
    assert (target / "mine.txt").read_text() == "my work\n"
    assert (target / ".git").exists()
    assert "Broken repo entry" in _summary(tmp_path)


def test_sync_file_survives_when_store_dir_is_unreadable(tmp_path: Path, origin_repo: Path):
    """Regression (Critical 2, round 2): a fail-closed isRepoEntry cannot
    fix this — `test -e`/`test -L` on a path inside an unreadable
    directory are both false for the same reason `test -f` was, so this
    plain (non-repo) tracked directory never even reaches isRepoEntry's
    guard. The real bug is in mirrorDir itself: its manual fallback finds
    nothing under an unreadable source, so listDirExtras reports every
    destination file as "extra" and deletes it — for ANY tracked
    directory, not only repo entries. mirrorDir must refuse to run when
    its source isn't readable, and syncDirToSystem must report that skip
    instead of silently mirroring nothing.

    chmod(0o000) on the store dir, restored in `finally` no matter what,
    so a failing assertion here can never leave an unremovable directory
    behind for pytest's tmp_path cleanup."""
    store = tmp_path / "store"
    store.mkdir(parents=True)
    (store / "init.lua").write_text("-- content\n")

    target = tmp_path / "sys" / "nvim"
    subprocess.run(["git", "clone", "--quiet", str(origin_repo), str(target)],
                   check=True, capture_output=True)
    (target / "mine.txt").write_text("my work\n")

    store.chmod(0o000)
    try:
        _run_sync_file(target, store, tmp_path)
    finally:
        store.chmod(0o755)

    assert (target / "README.md").is_file()
    assert (target / "mine.txt").read_text() == "my work\n"
    assert (target / ".git").exists()
    summary = _summary(tmp_path).lower()
    assert "skip" in summary


def test_sync_file_survives_when_store_has_unreadable_subdirectory(tmp_path: Path):
    """Regression (round 3): a source directory readable at its own top
    level but containing an unreadable subdirectory still let mirrorDir
    destroy the destination's counterparts under round 2's fix — rsync
    (or the manual find-based fallback) silently omits the subtree it
    cannot enter, and listDirExtras then reports the destination's files
    under it as "extra" and deletes them, even though the top-level
    readability check passes. The reviewer's reproduction: store
    readable, store/sub at mode 000, destination has sub/deep.lua and
    sub/keep.lua — both used to get deleted with two "Deleted file (dir
    sync)" summary lines plus "Updated directory".

    chmod(0o000) on the subdirectory only, restored in `finally` so a
    failing assertion can't leave an unremovable directory behind."""
    store = tmp_path / "store"
    store.mkdir(parents=True)
    (store / "top.txt").write_text("top\n")
    sub = store / "sub"
    sub.mkdir()
    (sub / "deep.lua").write_text("deep\n")

    target = tmp_path / "sys" / "nvim"
    target.mkdir(parents=True)
    (target / "top.txt").write_text("top\n")
    target_sub = target / "sub"
    target_sub.mkdir()
    (target_sub / "deep.lua").write_text("deep\n")
    (target_sub / "keep.lua").write_text("keep\n")

    sub.chmod(0o000)
    try:
        _run_sync_file(target, store, tmp_path)
    finally:
        sub.chmod(0o755)

    assert (target_sub / "deep.lua").read_text() == "deep\n"
    assert (target_sub / "keep.lua").read_text() == "keep\n"
    summary = _summary(tmp_path).lower()
    assert "skip" in summary


def test_capture_dir_from_system_skips_when_sysdir_has_unreadable_subdirectory(tmp_path: Path):
    """Same defect, opposite direction: captureDirFromSystem must refuse
    when its system-side source has an unreadable subdirectory, not only
    when the top level itself is unreadable. chmod restored in `finally`
    so a failing assertion can't leave an unremovable directory behind."""
    sysdir = tmp_path / "sys" / "nvim"
    sysdir.mkdir(parents=True)
    (sysdir / "top.txt").write_text("top\n")
    sub = sysdir / "sub"
    sub.mkdir()
    (sub / "deep.lua").write_text("deep\n")

    store = tmp_path / "store"
    store.mkdir(parents=True)
    (store / "top.txt").write_text("top\n")
    store_sub = store / "sub"
    store_sub.mkdir()
    (store_sub / "deep.lua").write_text("deep\n")
    (store_sub / "keep.lua").write_text("keep\n")

    sub.chmod(0o000)
    try:
        result = run_bash(f'captureDirFromSystem "{sysdir}" "{store}"; echo "rc=$?"', tmp_path)
    finally:
        sub.chmod(0o755)

    assert result.stdout.strip().splitlines()[-1] == "rc=2"
    assert (store_sub / "deep.lua").read_text() == "deep\n"
    assert (store_sub / "keep.lua").read_text() == "keep\n"
    summary = _summary(tmp_path).lower()
    assert "skip" in summary


def test_capture_repo_updates_marker_on_new_origin(tmp_path: Path, origin_repo: Path):
    store = tmp_path / "store"
    make_marker(store, "git@example.com:me/old.git", branch="main")
    target = tmp_path / "sys" / "nvim"
    subprocess.run(["git", "clone", "--quiet", str(origin_repo), str(target)],
                   check=True, capture_output=True)

    result = run_bash(f'captureRepoFromSystem "{target}" "{store}"; echo "rc=$?"', tmp_path)

    assert result.stdout.strip().splitlines()[-1] == "rc=0"
    marker = (store / ".ttgit").read_text()
    assert str(origin_repo) in marker
    assert "branch = main" in marker


def test_capture_repo_is_a_noop_when_marker_matches(tmp_path: Path, origin_repo: Path):
    store = tmp_path / "store"
    make_marker(store, str(origin_repo), branch="main")
    target = tmp_path / "sys" / "nvim"
    subprocess.run(["git", "clone", "--quiet", str(origin_repo), str(target)],
                   check=True, capture_output=True)
    before = (store / ".ttgit").read_text()

    result = run_bash(f'captureRepoFromSystem "{target}" "{store}"; echo "rc=$?"', tmp_path)

    assert result.stdout.strip().splitlines()[-1] == "rc=1"
    assert (store / ".ttgit").read_text() == before


def test_capture_repo_preserves_force_flag(tmp_path: Path, origin_repo: Path):
    store = tmp_path / "store"
    make_marker(store, "git@example.com:me/old.git", branch="main", force=True)
    target = tmp_path / "sys" / "nvim"
    subprocess.run(["git", "clone", "--quiet", str(origin_repo), str(target)],
                   check=True, capture_output=True)

    run_bash(f'captureRepoFromSystem "{target}" "{store}"', tmp_path)

    assert "force  = true" in (store / ".ttgit").read_text()


def test_capture_repo_preserves_uppercase_force_flag(tmp_path: Path, origin_repo: Path):
    """force = TRUE must survive a marker rewrite too. Both capture and
    sync must fold case the same way — round 1 folded only the sync-side
    comparison, so an uppercase force there was still honoured for
    `git reset --hard`, but capturing (e.g. after a new origin) silently
    dropped it because this comparison was still case-sensitive."""
    store = tmp_path / "store"
    store.mkdir(parents=True)
    (store / ".ttgit").write_text(
        "url    = git@example.com:me/old.git\nbranch = main\nforce  = TRUE\n"
    )
    target = tmp_path / "sys" / "nvim"
    subprocess.run(["git", "clone", "--quiet", str(origin_repo), str(target)],
                   check=True, capture_output=True)

    run_bash(f'captureRepoFromSystem "{target}" "{store}"', tmp_path)

    assert "force  = true" in (store / ".ttgit").read_text()


def test_capture_repo_leaves_marker_when_target_is_not_a_repo(tmp_path: Path):
    store = tmp_path / "store"
    make_marker(store, "git@example.com:me/r.git")
    target = tmp_path / "sys" / "nvim"
    target.mkdir(parents=True)
    before = (store / ".ttgit").read_text()

    result = run_bash(f'captureRepoFromSystem "{target}" "{store}"; echo "rc=$?"', tmp_path)

    assert result.stdout.strip().splitlines()[-1] == "rc=2"
    assert (store / ".ttgit").read_text() == before


def test_capture_repo_reports_failure_when_marker_path_is_a_directory(
    tmp_path: Path, origin_repo: Path
):
    """Regression: the marker-write redirect can itself fail (.ttgit is a
    directory, which isRepoEntry's fail-closed predicate now routes to
    captureRepoFromSystem instead of to mirrorDir). Nothing is destroyed
    by that routing, but captureRepoFromSystem must not claim success —
    rc must be 2 and no "Updated repo marker" note may appear."""
    store = tmp_path / "store"
    store.mkdir(parents=True)
    (store / ".ttgit").mkdir()  # marker path exists but is a directory

    target = tmp_path / "sys" / "nvim"
    subprocess.run(["git", "clone", "--quiet", str(origin_repo), str(target)],
                   check=True, capture_output=True)

    result = run_bash(f'captureRepoFromSystem "{target}" "{store}"; echo "rc=$?"', tmp_path)

    assert result.stdout.strip().splitlines()[-1] == "rc=2"
    assert (store / ".ttgit").is_dir()
    assert "Updated repo marker" not in _summary(tmp_path)


def test_capture_dir_from_system_refuses_to_overwrite_a_marker(tmp_path: Path):
    """Regression: without a guard, mirrorDir would replace .ttgit with the
    repo's contents."""
    store = tmp_path / "store"
    make_marker(store, "git@example.com:me/r.git")
    target = tmp_path / "sys" / "nvim"
    target.mkdir(parents=True)
    (target / "init.lua").write_text("-- content\n")

    run_bash(f'captureDirFromSystem "{target}" "{store}"', tmp_path)

    assert (store / ".ttgit").is_file()
    assert not (store / "init.lua").exists()


def test_capture_dir_from_system_skips_when_sysdir_is_unreadable(tmp_path: Path):
    """Same defect as the syncFile/mirrorDir regression, opposite
    direction: captureDirFromSystem must refuse to mirror when its
    system-side source is unreadable, instead of emptying the TT store
    side. chmod restored in `finally` so a failing assertion can't leave
    an unremovable directory behind."""
    sysdir = tmp_path / "sys" / "nvim"
    sysdir.mkdir(parents=True)
    (sysdir / "init.lua").write_text("-- content\n")

    store = tmp_path / "store"
    store.mkdir(parents=True)
    (store / "init.lua").write_text("-- old content\n")

    sysdir.chmod(0o000)
    try:
        result = run_bash(f'captureDirFromSystem "{sysdir}" "{store}"; echo "rc=$?"', tmp_path)
    finally:
        sysdir.chmod(0o755)

    assert result.stdout.strip().splitlines()[-1] == "rc=2"
    assert (store / "init.lua").read_text() == "-- old content\n"
    summary = _summary(tmp_path).lower()
    assert "skip" in summary


# --- I4: the marker's branch is never enforced ----------------------------


def test_sync_repo_refuses_force_reset_on_a_branch_the_marker_never_named(
    tmp_path: Path, origin_repo: Path
):
    """I4: `git pull --ff-only` and `git reset --hard origin/<marker branch>`
    both act on whatever branch is checked out, while ahead/behind is
    computed against origin/<marker branch>. A user on a side branch was
    therefore permanently reported as diverged — and with force = true the
    reset ran on that side branch, orphaning their commits."""
    store = tmp_path / "store"
    make_marker(store, str(origin_repo), force=True)
    target = tmp_path / "sys" / "nvim"
    subprocess.run(["git", "clone", "--quiet", str(origin_repo), str(target)],
                   check=True, capture_output=True)
    _git(target, "config", "user.email", "t@example.com")
    _git(target, "config", "user.name", "Test")
    _git(target, "checkout", "--quiet", "-b", "wip")
    (target / "my_work.txt").write_text("hours of it\n")
    _git(target, "add", "my_work.txt")
    _git(target, "commit", "--quiet", "-m", "my work")

    # move origin/main ahead, so ahead>0 and behind>0 and the force branch
    # of syncRepoToSystem is the one that runs
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

    assert (target / "my_work.txt").read_text() == "hours of it\n"
    summary = _summary(tmp_path)
    assert "branch" in summary
    assert "Reset repo" not in summary


def test_sync_repo_syncs_normally_when_head_matches_the_marker_branch(
    tmp_path: Path, origin_repo: Path
):
    """Parity guard for the check above: it must not fire on the happy path."""
    store = tmp_path / "store"
    make_marker(store, str(origin_repo), force=True)
    target = tmp_path / "sys" / "nvim"
    subprocess.run(["git", "clone", "--quiet", str(origin_repo), str(target)],
                   check=True, capture_output=True)
    (target / "junk.txt").write_text("junk\n")

    run_bash(f'syncRepoToSystem "{store}" "{target}"', tmp_path)

    assert not (target / "junk.txt").exists()
    assert "Reset repo" in _summary(tmp_path)
