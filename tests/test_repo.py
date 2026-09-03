"""Tests for git-repo tracking (tui/core/repo.py)."""

from pathlib import Path

import pytest

from tui.core.repo import MARKER_NAME, RepoSpec, classify, read_marker, write_marker


@pytest.mark.parametrize("state,bucket", [
    ("ok", "synced"), ("ahead", "synced"),
    ("behind", "changed"), ("dirty", "changed"), ("diverged", "changed"),
    ("missing", "missing"),
    ("not_a_repo", "broken"), ("wrong_origin", "broken"), ("invalid_spec", "broken"),
])
def test_classify_buckets_every_status(state: str, bucket: str):
    assert classify(state) == bucket


def test_every_status_has_a_bucket():
    """_BUCKETS must cover exactly the statuses status() can return — this is
    the assertion that goes red when someone adds a status and forgets the
    bucket, which the old `in {…}` form could never do."""
    from tui.core.repo import ALL_STATUSES, _BUCKETS
    assert sorted(_BUCKETS) == sorted(ALL_STATUSES)


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


def test_read_marker_keys_are_case_sensitive(tmp_path: Path):
    """The bash parser in bin/include.sh matches keys case-sensitively, so
    Python must too — otherwise the two disagree on the same file."""
    (tmp_path / MARKER_NAME).write_text("URL = git@example.com:me/r.git\n")
    spec = read_marker(tmp_path)
    assert spec is not None
    assert spec.url == ""


def test_a_directory_marker_reads_as_a_broken_repo_entry(tmp_path: Path):
    """R21: is_file() is False for a directory named .ttgit, which used to
    make read_marker return None — treating the entry as plain content and
    disarming the repo guard in _do_apply (rmtree + copytree over a real
    repo). It must instead be reported as a broken repo entry (invalid_spec),
    never as "not a repo entry at all"."""
    from tui.core.repo import status

    (tmp_path / MARKER_NAME).mkdir()
    spec = read_marker(tmp_path)
    assert spec is not None
    assert spec.url == ""
    assert status(tmp_path / "wherever", spec) == "invalid_spec"


def test_a_directory_marker_still_reads_as_is_repo(tmp_path: Path):
    """Same regression as above, checked at the FileMapping level: is_repo
    must stay True for a malformed (directory) marker so the sync/apply
    guards that gate on it stay armed instead of silently falling through
    to plain-file handling."""
    from tui.core.config import FileMapping

    (tmp_path / MARKER_NAME).mkdir()
    mapping = FileMapping(
        stored="myrepo", target=".myrepo", config="common", repo_path=tmp_path
    )
    assert mapping.is_repo is True


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


def _push_remote_commit(tmp_path: Path, origin_repo: Path, name: str = "remote.txt") -> None:
    """Clone origin_repo into a throwaway checkout, commit a new file there,
    and push it — simulates someone else moving the remote branch forward
    while our `clone` fixture's checkout stays where it was."""
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin_repo), str(other)],
        check=True, capture_output=True,
    )
    _run(other, "git", "config", "user.email", "t@example.com")
    _run(other, "git", "config", "user.name", "Test")
    (other / name).write_text("remote\n")
    _run(other, "git", "add", name)
    _run(other, "git", "commit", "--quiet", "-m", "remote")
    _run(other, "git", "push", "--quiet", "origin", "main")


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


from tui.core.repo import ahead_behind, status


def test_status_invalid_spec_without_url(clone: Path):
    assert status(clone, RepoSpec(url="")) == "invalid_spec"


def test_status_missing_when_path_absent(tmp_path: Path):
    assert status(tmp_path / "nope", RepoSpec(url="u")) == "missing"


def test_status_not_a_repo_for_plain_directory(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert status(plain, RepoSpec(url="u")) == "not_a_repo"


def test_status_wrong_origin(clone: Path):
    assert status(clone, RepoSpec(url="git@example.com:other/repo.git")) == "wrong_origin"


def test_status_ok_for_clean_clone(clone: Path, origin_repo: Path):
    assert status(clone, RepoSpec(url=str(origin_repo), branch="main")) == "ok"


def test_status_dirty_with_uncommitted_changes(clone: Path, origin_repo: Path):
    (clone / "README.md").write_text("changed\n")
    assert status(clone, RepoSpec(url=str(origin_repo), branch="main")) == "dirty"


def test_status_dirty_with_untracked_file(clone: Path, origin_repo: Path):
    (clone / "new.txt").write_text("x\n")
    assert status(clone, RepoSpec(url=str(origin_repo), branch="main")) == "dirty"


def test_status_ahead_with_local_commit(clone: Path, origin_repo: Path):
    (clone / "local.txt").write_text("local\n")
    _run(clone, "git", "add", "local.txt")
    _run(clone, "git", "commit", "--quiet", "-m", "local")
    assert status(clone, RepoSpec(url=str(origin_repo), branch="main")) == "ahead"


def test_status_behind_when_remote_moved(clone: Path, origin_repo: Path, tmp_path: Path):
    _push_remote_commit(tmp_path, origin_repo)

    assert status(clone, RepoSpec(url=str(origin_repo), branch="main"), fetch=True) == "behind"


def test_status_diverged(clone: Path, origin_repo: Path, tmp_path: Path):
    _push_remote_commit(tmp_path, origin_repo)

    (clone / "local.txt").write_text("local\n")
    _run(clone, "git", "add", "local.txt")
    _run(clone, "git", "commit", "--quiet", "-m", "local")

    assert status(clone, RepoSpec(url=str(origin_repo), branch="main"), fetch=True) == "diverged"


def test_dirty_beats_behind(clone: Path, origin_repo: Path, tmp_path: Path):
    """Precedence matters: a dirty repo is skipped regardless of how far
    behind it is, so `dirty` must win."""
    _push_remote_commit(tmp_path, origin_repo)

    (clone / "README.md").write_text("dirty\n")
    assert status(clone, RepoSpec(url=str(origin_repo), branch="main"), fetch=True) == "dirty"


def test_ahead_behind_counts(clone: Path):
    assert ahead_behind(clone, "main") == (0, 0)


from tui.core.repo import sync_to_system


def test_sync_clones_when_target_missing(tmp_path: Path, origin_repo: Path):
    target = tmp_path / "fresh"
    result = sync_to_system(target, RepoSpec(url=str(origin_repo), branch="main"))
    assert result.action == "cloned"
    assert (target / "README.md").read_text() == "one\n"


def test_sync_backs_up_non_repo_directory_then_clones(tmp_path: Path, origin_repo: Path):
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "old.txt").write_text("old\n")
    result = sync_to_system(target, RepoSpec(url=str(origin_repo), branch="main"))
    assert result.action == "cloned"
    assert (target / "README.md").is_file()
    assert (tmp_path / "occupied.ttbak" / "old.txt").read_text() == "old\n"


def test_sync_is_a_noop_when_up_to_date(clone: Path, origin_repo: Path):
    result = sync_to_system(clone, RepoSpec(url=str(origin_repo), branch="main"))
    assert result.action == "uptodate"


def test_sync_pulls_when_behind(clone: Path, origin_repo: Path, tmp_path: Path):
    _push_remote_commit(tmp_path, origin_repo)

    result = sync_to_system(clone, RepoSpec(url=str(origin_repo), branch="main"))
    assert result.action == "pulled"
    assert (clone / "remote.txt").is_file()


def test_sync_skips_dirty_repo_and_keeps_local_work(clone: Path, origin_repo: Path):
    (clone / "README.md").write_text("my work\n")
    result = sync_to_system(clone, RepoSpec(url=str(origin_repo), branch="main"))
    assert result.action == "skipped"
    assert (clone / "README.md").read_text() == "my work\n"


def test_sync_resets_dirty_repo_when_force_is_set(clone: Path, origin_repo: Path):
    (clone / "README.md").write_text("my work\n")
    (clone / "junk.txt").write_text("junk\n")
    result = sync_to_system(clone, RepoSpec(url=str(origin_repo), branch="main", force=True))
    assert result.action == "reset"
    assert (clone / "README.md").read_text() == "one\n"
    assert not (clone / "junk.txt").exists()


def test_sync_skips_when_remote_is_unreachable(clone: Path, origin_repo: Path):
    """R30: a `git fetch` failure (no network, origin gone) must not fall
    through to whatever ahead_behind() computes from stale/absent remote
    refs — that used to report a repo that was never actually reached as
    merely 'up to date'. Deleting the bare origin after cloning (mirroring
    the bash-side test) reproduces 'remote unreachable' fully offline: no
    real network is ever touched."""
    import shutil
    shutil.rmtree(origin_repo)

    before = (clone / "README.md").read_text()
    result = sync_to_system(clone, RepoSpec(url=str(origin_repo), branch="main"))

    assert result.action == "skipped"
    assert str(origin_repo) in result.message
    assert (clone / "README.md").read_text() == before


def test_sync_skips_on_origin_mismatch(clone: Path):
    before = (clone / "README.md").read_text()
    result = sync_to_system(clone, RepoSpec(url="git@example.com:other.git", branch="main"))
    assert result.action == "skipped"
    assert (clone / "README.md").read_text() == before


def test_sync_fails_on_invalid_spec(clone: Path):
    assert sync_to_system(clone, RepoSpec(url="")).action == "failed"


# --- I1: "is a repo root" and "has an origin remote" are two questions -----


@pytest.fixture
def clone_without_origin(clone: Path) -> Path:
    """A live repository whose remote was renamed origin -> upstream.

    Still a repo root, still full of the user's work — it simply is not the
    repo the marker names any more."""
    _run(clone, "git", "remote", "rename", "origin", "upstream")
    (clone / "work_in_progress.txt").write_text("precious\n")
    return clone


def test_repo_root_is_independent_of_the_origin_remote(clone_without_origin: Path):
    """bash splits these: ttGitTopLevel checks only the root, and the origin
    comparison is a separate, non-destructive row."""
    from tui.core.repo import repo_root

    assert repo_root(clone_without_origin) == clone_without_origin.resolve()
    assert repo_root(clone_without_origin / "nope") is None


def test_origin_url_is_none_without_an_origin_remote(clone_without_origin: Path, clone: Path):
    from tui.core.repo import origin_url

    assert origin_url(clone_without_origin) is None


def test_detect_still_requires_both_root_and_origin(clone_without_origin: Path):
    """detect()'s contract is unchanged: it answers "a repo root with an
    origin I can record", which is what the add flow and the migration need."""
    from tui.core.repo import detect

    assert detect(clone_without_origin) is None


def test_status_says_wrong_origin_not_not_a_repo_when_origin_is_gone(clone_without_origin: Path):
    """I1: status() conflated the two questions, so a live repository whose
    remote had been renamed was reported as `not_a_repo` — and
    sync_to_system's "not a git repository" branch then renamed it to
    .ttbak and cloned over it."""
    from tui.core.repo import status

    assert status(clone_without_origin, RepoSpec(url="whatever")) == "wrong_origin"


def test_sync_to_system_never_moves_aside_a_repo_that_lost_its_origin(
    clone_without_origin: Path, origin_repo: Path
):
    """The destructive half of I1, reproduced: bash reports "Skipped repo
    (origin mismatch)" and leaves the tree in place; Python renamed it to
    .ttbak and cloned over it, moving the user's files out from under them."""
    from tui.core.repo import sync_to_system

    result = sync_to_system(clone_without_origin, RepoSpec(url=str(origin_repo)))

    assert result.action == "skipped"
    assert "origin" in result.message
    assert (clone_without_origin / "work_in_progress.txt").read_text() == "precious\n"
    assert not clone_without_origin.with_name(clone_without_origin.name + ".ttbak").exists()


# --- I4: the marker's branch is never enforced ----------------------------


@pytest.fixture
def clone_on_side_branch(tmp_path: Path, clone: Path, origin_repo: Path) -> Path:
    """The user is on `wip` with a commit of their own; the marker says
    `main`, and origin/main has moved ahead."""
    _run(clone, "git", "checkout", "--quiet", "-b", "wip")
    (clone / "my_work.txt").write_text("hours of it\n")
    _run(clone, "git", "add", "my_work.txt")
    _run(clone, "git", "commit", "--quiet", "-m", "my work")
    _push_remote_commit(tmp_path, origin_repo)
    _run(clone, "git", "fetch", "--quiet", "origin")
    return clone


def test_status_reports_a_branch_mismatch_instead_of_diverged(clone_on_side_branch: Path, origin_repo: Path):
    """I4: ahead/behind is computed against origin/<marker branch>, so a
    user sitting on a side branch was permanently `diverged` — with a detail
    pane saying "Diverged from the remote", which is not what happened."""
    from tui.core.repo import status

    spec = RepoSpec(url=str(origin_repo), branch="main")
    assert status(clone_on_side_branch, spec) == "wrong_branch"


def test_wrong_branch_has_a_bucket(clone_on_side_branch: Path):
    from tui.core.repo import classify

    assert classify("wrong_branch") == "broken"


def test_status_is_not_wrong_branch_when_the_marker_names_no_branch(
    clone_on_side_branch: Path, origin_repo: Path
):
    """No `branch` in the marker means "whatever is checked out" — there is
    nothing to mismatch."""
    from tui.core.repo import status

    assert status(clone_on_side_branch, RepoSpec(url=str(origin_repo))) != "wrong_branch"


def test_sync_refuses_the_force_reset_on_a_branch_the_marker_never_named(
    clone_on_side_branch: Path, origin_repo: Path
):
    """The destructive half of I4: with force = true, sync ran
    `git reset --hard origin/main` *while on wip*, orphaning the user's
    commits, and then `git clean -fd`."""
    from tui.core.repo import sync_to_system

    spec = RepoSpec(url=str(origin_repo), branch="main", force=True)
    result = sync_to_system(clone_on_side_branch, spec)

    assert result.action == "skipped"
    assert "wip" in result.message and "main" in result.message
    assert (clone_on_side_branch / "my_work.txt").read_text() == "hours of it\n"
    _, head = _read_head(clone_on_side_branch)
    assert head == "wip"


def _read_head(path: Path) -> tuple[int, str]:
    import subprocess as _sp
    proc = _sp.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                   cwd=path, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip()


def test_sync_refuses_the_force_reset_on_a_detached_head(clone: Path, origin_repo: Path):
    from tui.core.repo import sync_to_system

    _run(clone, "git", "checkout", "--quiet", "--detach", "HEAD")
    result = sync_to_system(clone, RepoSpec(url=str(origin_repo), branch="main", force=True))

    assert result.action == "skipped"
    assert "main" in result.message
