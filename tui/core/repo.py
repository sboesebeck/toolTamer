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
        values[key.strip().lower()] = value.strip()
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
