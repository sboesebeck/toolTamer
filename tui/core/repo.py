"""Git-repo entries in the ToolTamer store.

A tracked directory whose store side contains only a `.ttgit` marker is a
repo entry: ToolTamer records where the repository comes from and syncs it
with clone/pull instead of mirroring file contents.

The marker format is deliberately trivial (`key = value`, `#` starts a
comment) because bin/include.sh parses the same file with grep and cut.
Values must not contain `#`.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

MARKER_NAME = ".ttgit"


@dataclass
class RepoSpec:
    url: str
    branch: str | None = None
    force: bool = False


def read_marker(store_dir: Path) -> RepoSpec | None:
    """Parse the `.ttgit` marker in `store_dir`.

    Returns None when there is no marker. A marker without a `url` yields a
    RepoSpec with an empty url — callers report that as `invalid_spec`
    rather than silently treating the entry as a plain directory.

    R21: `marker.is_file()` is False both when there is truly no marker AND
    when `.ttgit` exists but is a directory (or some other non-regular-file
    entry) — and treating that second case as "no marker" used to make
    FileMapping.is_repo False, disarming the repo guard in
    FileScreen._do_apply and letting it rmtree+copytree over a real repo.
    So the existence check here is deliberately broader than "is a regular
    file": anything at all that exists at the marker path counts as a
    marker, and read_text() below (via its except clause) is what turns an
    unreadable one into a reported `invalid_spec` rather than silence. This
    is the safe direction to err in: an ambiguous marker path is treated as
    a repo entry, never as a plain directory to be mirrored.
    """
    marker = store_dir / MARKER_NAME
    if not (marker.exists() or marker.is_symlink()):
        return None
    values: dict[str, str] = {}
    try:
        text = marker.read_text()
    except (OSError, UnicodeDecodeError):
        return RepoSpec(url="")
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    branch = values.get("branch") or None
    return RepoSpec(
        url=values.get("url", ""),
        branch=branch,
        force=values.get("force", "").lower() == "true",
    )


def write_marker(store_dir: Path, spec: RepoSpec) -> None:
    """Write the `.ttgit` marker, creating `store_dir` if needed."""
    store_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"url    = {spec.url}"]
    if spec.branch:
        lines.append(f"branch = {spec.branch}")
    if spec.force:
        lines.append("force  = true")
    (store_dir / MARKER_NAME).write_text("\n".join(lines) + "\n")


def git_available() -> bool:
    import shutil
    return shutil.which("git") is not None


def _git(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    """Run git, never raise. Returns (returncode, stripped stdout).

    A missing git binary yields (127, "") so callers can treat it like any
    other failure instead of crashing the TUI."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True, text=True,
        )
    except (FileNotFoundError, OSError):
        return 127, ""
    return proc.returncode, proc.stdout.strip()


def repo_root(system_path: Path) -> Path | None:
    """Return the resolved path when `system_path` is the ROOT of a git
    repository, else None. Says nothing about remotes.

    The counterpart of ttGitTopLevel in bin/include.sh, and split out of
    detect() for the same reason bash keeps them apart: "is this a repo
    root" and "does it have the origin the marker names" are two questions
    with two very different answers. Folding them together made a live
    repository whose remote had merely been renamed look like "not a git
    repository", which is the one classification that authorises moving the
    tree aside and cloning over it.

    Only the root counts: a subdirectory of a repo is not itself trackable
    as a repo entry."""
    if not system_path.is_dir():
        return None
    rc, top = _git(["rev-parse", "--show-toplevel"], cwd=system_path)
    if rc != 0 or not top:
        return None
    try:
        resolved = system_path.resolve()
        if Path(top).resolve() != resolved:
            return None
    except OSError:
        return None
    return resolved


def origin_url(system_path: Path) -> str | None:
    """The `origin` remote URL of the repo at `system_path`, or None when
    there is no origin (or no repo)."""
    rc, url = _git(["remote", "get-url", "origin"], cwd=system_path)
    if rc != 0 or not url:
        return None
    return url


def current_branch(system_path: Path) -> str | None:
    """The checked-out branch name, or None on a detached HEAD / no repo."""
    rc, branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=system_path)
    if rc != 0 or not branch or branch == "HEAD":
        return None
    return branch


def detect(system_path: Path) -> RepoSpec | None:
    """Return a RepoSpec when `system_path` is the root of a git repo with
    an `origin` remote, else None.

    Contract deliberately unchanged: this is the "a repo root with an origin
    I can record" question, which is what the add flow and the convert-to-repo
    migration need. Callers that only want to know whether a path is a repo
    root — status(), sync_to_system() — use repo_root() instead."""
    if repo_root(system_path) is None:
        return None
    url = origin_url(system_path)
    if url is None:
        return None
    return RepoSpec(url=url, branch=current_branch(system_path))


RepoStatus = str  # one of the ten literals documented in the plan/spec

ALL_STATUSES = (
    "ok", "ahead", "behind", "dirty", "diverged",
    "missing", "not_a_repo", "wrong_origin", "wrong_branch", "invalid_spec",
)

_BUCKETS = {
    "ok": "synced", "ahead": "synced",
    "behind": "changed", "dirty": "changed", "diverged": "changed",
    "missing": "missing",
    "not_a_repo": "broken", "wrong_origin": "broken",
    "wrong_branch": "broken", "invalid_spec": "broken",
}


def classify(state: RepoStatus) -> str:
    """Bucket a repo status for display: synced | changed | missing | broken.

    Both the file list and the status bar need this mapping, and they used to
    encode it separately — which is how a synced repo entry ended up counted
    as "changed" in the status bar. One definition, two consumers.

    Raises KeyError for a state not in _BUCKETS rather than defaulting it to
    "broken": status() is the only producer of these values and lives in
    this same module, so an unmapped state is a bug here, and R23 wants that
    caught by test_every_status_has_a_bucket rather than silently mislabeled
    for a user."""
    return _BUCKETS[state]


def _effective_branch(system_path: Path, spec: RepoSpec) -> str:
    if spec.branch:
        return spec.branch
    _, branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=system_path)
    return branch or "HEAD"


def ahead_behind(system_path: Path, branch: str) -> tuple[int, int]:
    """Commits the local branch is ahead of / behind origin/<branch>.

    Returns (0, 0) when the comparison is not possible (no such remote
    branch, detached HEAD, ...) — callers then see 'ok' rather than a
    misleading sync prompt."""
    rc, out = _git(
        ["rev-list", "--left-right", "--count", f"HEAD...origin/{branch}"],
        cwd=system_path,
    )
    if rc != 0 or not out:
        return 0, 0
    parts = out.split()
    if len(parts) != 2:
        return 0, 0
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return 0, 0


def status(system_path: Path, spec: RepoSpec, fetch: bool = False) -> RepoStatus:
    """Classify a repo entry. See the plan for the precedence order.

    `fetch=False` keeps this cheap and offline: the TUI recomputes it on
    every refresh. Sync paths pass fetch=True."""
    if not spec.url:
        return "invalid_spec"
    if not system_path.exists():
        return "missing"
    if repo_root(system_path) is None:
        return "not_a_repo"
    # I1: a repo root without an origin is still a repository — just not the
    # one the marker names. That is what `wrong_origin` already means, so it
    # gets no tenth status of its own; what it must NOT be is `not_a_repo`,
    # the value that authorises sync_to_system to move the tree aside.
    if origin_url(system_path) != spec.url:
        return "wrong_origin"
    # I4: everything below compares against origin/<spec.branch>, while pull
    # and reset act on whatever is checked out. Sitting on a side branch made
    # a repo permanently "diverged" — a description of something that never
    # happened — and authorised `git reset --hard origin/<spec.branch>` on a
    # branch the marker never named. Its own state, ranked with the other
    # "this working copy is not what the marker describes" answers.
    if spec.branch and current_branch(system_path) != spec.branch:
        return "wrong_branch"
    if fetch:
        _git(["fetch", "--quiet", "origin"], cwd=system_path)
    rc, porcelain = _git(["status", "--porcelain"], cwd=system_path)
    if rc == 0 and porcelain:
        return "dirty"
    ahead, behind = ahead_behind(system_path, _effective_branch(system_path, spec))
    if ahead and behind:
        return "diverged"
    if behind:
        return "behind"
    if ahead:
        return "ahead"
    return "ok"


@dataclass
class SyncResult:
    action: str  # cloned | pulled | reset | uptodate | skipped | failed
    message: str


def clone(system_path: Path, spec: RepoSpec) -> bool:
    """Clone spec.url into system_path. Returns True on success."""
    args = ["clone", "--quiet"]
    if spec.branch:
        args += ["--branch", spec.branch]
    args += [spec.url, str(system_path)]
    system_path.parent.mkdir(parents=True, exist_ok=True)
    rc, _ = _git(args)
    return rc == 0


def pull(system_path: Path, spec: RepoSpec) -> bool:
    """Fast-forward-only pull. Returns True on success."""
    rc, _ = _git(["pull", "--quiet", "--ff-only"], cwd=system_path)
    return rc == 0


def sync_to_system(system_path: Path, spec: RepoSpec) -> SyncResult:
    """Bring `system_path` in line with `spec`. Never destroys local work
    unless spec.force is set. Mirrors syncRepoToSystem in bin/include.sh."""
    import shutil

    if not spec.url:
        return SyncResult("failed", f"{system_path}: .ttgit has no url")
    if not git_available():
        return SyncResult("skipped", f"{system_path}: git is not installed")

    if not system_path.exists():
        if clone(system_path, spec):
            return SyncResult("cloned", f"Cloned {spec.url} into {system_path}")
        return SyncResult("failed", f"Clone of {spec.url} failed")

    if repo_root(system_path) is None:
        # .ttbak is a single-slot scratch backup, same convention as
        # syncDirToSystem/syncFile in bin/include.sh and bin/tt: a stale
        # one is replaced rather than kept around forever. The live tree
        # itself is never destroyed here — it is moved aside, not deleted.
        backup = system_path.with_name(system_path.name + ".ttbak")
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        system_path.rename(backup)
        if clone(system_path, spec):
            return SyncResult("cloned", f"Replaced non-repo {system_path} (backup: {backup})")
        return SyncResult("failed", f"Clone of {spec.url} failed (backup: {backup})")

    # I1/bash parity: the origin comparison happens here, before the fetch,
    # exactly where syncRepoToSystem does it. A repo whose origin does not
    # match the marker is skipped as "origin mismatch" rather than being
    # reported as unreachable by the fetch below (which, with no origin at
    # all, cannot possibly succeed).
    if origin_url(system_path) != spec.url:
        return SyncResult("skipped", f"{system_path}: origin differs from .ttgit ({spec.url})")

    # I4: refuse before the fetch, and long before the force reset. Checking
    # out spec.branch on the user's behalf would discard the context they are
    # working in without asking; saying which branch is checked out and which
    # the marker names lets them choose (checkout, or `u` to record where they
    # are). Mirrors the same check in syncRepoToSystem.
    if spec.branch:
        head = current_branch(system_path)
        if head != spec.branch:
            return SyncResult(
                "skipped",
                f"{system_path}: on {head or 'a detached HEAD'} but .ttgit names "
                f"{spec.branch} — not touched",
            )

    # R30: status()'s own fetch=True discards git fetch's exit code, so an
    # unreachable remote (no network, origin gone) fell through to whatever
    # ahead_behind() computed from stale/absent remote refs — reporting a
    # repo that was never actually reached as merely "up to date". The sync
    # path needs to see that failure, so it fetches here itself and bails
    # before asking status() for the (now offline) classification. Deliberately
    # not a tenth RepoStatus value: reachability only matters to the sync
    # path, not to the offline list/status-bar refresh, so it stays local to
    # this SyncResult rather than rippling through classify()/ALL_STATUSES.
    rc, _ = _git(["fetch", "--quiet", "origin"], cwd=system_path)
    if rc != 0:
        return SyncResult("skipped", f"{system_path}: remote unreachable ({spec.url})")
    state = status(system_path, spec, fetch=False)
    if state == "wrong_origin":
        return SyncResult("skipped", f"{system_path}: origin differs from .ttgit")
    if state in ("dirty", "diverged"):
        if not spec.force:
            return SyncResult("skipped", f"{system_path}: local changes — not touched")
        branch = _effective_branch(system_path, spec)
        rc_reset, _ = _git(["reset", "--hard", f"origin/{branch}"], cwd=system_path)
        rc_clean, _ = _git(["clean", "-fd"], cwd=system_path)
        if rc_reset == 0 and rc_clean == 0:
            return SyncResult("reset", f"{system_path}: reset to origin/{branch} (force)")
        return SyncResult("failed", f"{system_path}: reset failed")
    if state == "behind":
        if pull(system_path, spec):
            return SyncResult("pulled", f"Updated {system_path}")
        return SyncResult("failed", f"{system_path}: pull failed")
    return SyncResult("uptodate", f"{system_path}: up to date")
