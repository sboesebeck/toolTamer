"""Git-repo entries in the ToolTamer store.

A tracked directory whose store side contains only a `.ttgit` marker is a
repo entry: ToolTamer records where the repository comes from and syncs it
with clone/pull instead of mirroring file contents.

The marker format is deliberately trivial (`key = value`, `#` starts a
comment) because bin/include.sh parses the same file with grep and cut.
Values must not contain `#`.
"""

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
