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
    """
    marker = store_dir / MARKER_NAME
    if not marker.is_file():
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


def detect(system_path: Path) -> RepoSpec | None:
    """Return a RepoSpec when `system_path` is the root of a git repo with
    an `origin` remote, else None.

    Only the root counts: a subdirectory of a repo is not itself trackable
    as a repo entry."""
    if not system_path.is_dir():
        return None
    rc, top = _git(["rev-parse", "--show-toplevel"], cwd=system_path)
    if rc != 0 or not top:
        return None
    try:
        if Path(top).resolve() != system_path.resolve():
            return None
    except OSError:
        return None
    rc, url = _git(["remote", "get-url", "origin"], cwd=system_path)
    if rc != 0 or not url:
        return None
    rc, branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=system_path)
    if rc != 0 or not branch or branch == "HEAD":
        branch = ""
    return RepoSpec(url=url, branch=branch or None)


RepoStatus = str  # one of the nine literals documented in the plan/spec

ALL_STATUSES = (
    "ok", "ahead", "behind", "dirty", "diverged",
    "missing", "not_a_repo", "wrong_origin", "invalid_spec",
)

_BUCKETS = {
    "ok": "synced", "ahead": "synced",
    "behind": "changed", "dirty": "changed", "diverged": "changed",
    "missing": "missing",
    "not_a_repo": "broken", "wrong_origin": "broken", "invalid_spec": "broken",
}


def classify(state: RepoStatus) -> str:
    """Bucket a repo status for display: synced | changed | missing | broken.

    Both the file list and the status bar need this mapping, and they used to
    encode it separately — which is how a synced repo entry ended up counted
    as "changed" in the status bar. One definition, two consumers."""
    return _BUCKETS.get(state, "broken")


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
    found = detect(system_path)
    if found is None:
        return "not_a_repo"
    if found.url != spec.url:
        return "wrong_origin"
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

    if detect(system_path) is None:
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

    state = status(system_path, spec, fetch=True)
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
