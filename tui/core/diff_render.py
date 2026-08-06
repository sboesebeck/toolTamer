"""Pure (no-Textual) logic for rendering unified diffs of the files that
changed inside a tracked directory. Kept separate from
tui/screens/files.py so the decision logic — caps, ordering, per-file error
handling — can be unit tested without driving the Textual worker/RichLog
machinery.

See docs/superpowers/specs/2026-08-06-dir-diff-changed-files-design.md.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

MAX_DIFF_FILES = 10
MAX_TOTAL_DIFF_LINES = 300
MAX_LINES_PER_FILE = 100


@dataclass
class ChangedFileDiff:
    """What to render for one path in `changed`. At most one of
    diff_lines/binary_line/symlink_line/error is set; all are None when
    the entry was skipped because a budget was already exhausted."""

    rel: str
    diff_lines: list[str] | None = None
    binary_line: str | None = None
    symlink_line: str | None = None
    error: str | None = None


@dataclass
class ChangedDiffsResult:
    files: list[ChangedFileDiff]
    truncated: bool = False
    diff_unavailable: bool = False


def _symlink_target(path: Path) -> str:
    if not path.is_symlink():
        return "(not a symlink)"
    try:
        return os.readlink(path)
    except OSError:
        return "(could not read link target)"


def _format_symlink_line(repo_path: Path, sys_path: Path) -> str:
    return (
        f"symlink: repo -> {_symlink_target(repo_path)}   "
        f"system -> {_symlink_target(sys_path)}"
    )


def render_changed_diffs(
    repo_dir: Path,
    sys_dir: Path,
    changed: list[str],
    *,
    max_diffs: int = MAX_DIFF_FILES,
    max_total_lines: int = MAX_TOTAL_DIFF_LINES,
    max_lines_per_file: int = MAX_LINES_PER_FILE,
) -> ChangedDiffsResult:
    """Decide what to show for each path in `changed` (already computed by
    `dir_diff`). Does not touch Textual — the caller maps the result to
    styled log lines."""
    results: list[ChangedFileDiff] = []
    diffs_shown = 0
    total_lines = 0
    diff_unavailable = False
    truncated = False

    for rel in changed:
        repo_path = repo_dir / rel
        sys_path = sys_dir / rel

        if diff_unavailable:
            results.append(ChangedFileDiff(rel=rel))
            continue
        if diffs_shown >= max_diffs or total_lines >= max_total_lines:
            results.append(ChangedFileDiff(rel=rel))
            truncated = True
            continue

        if repo_path.is_symlink() or sys_path.is_symlink():
            results.append(
                ChangedFileDiff(rel=rel, symlink_line=_format_symlink_line(repo_path, sys_path))
            )
            diffs_shown += 1
            continue

        try:
            proc = subprocess.run(
                ["diff", "-u", str(repo_path), str(sys_path)],
                capture_output=True, text=True, timeout=5,
            )
        except FileNotFoundError:
            diff_unavailable = True
            results.append(ChangedFileDiff(rel=rel))
            continue
        except subprocess.TimeoutExpired:
            results.append(ChangedFileDiff(rel=rel, error="(diff timed out)"))
            diffs_shown += 1
            continue
        except OSError as exc:
            results.append(ChangedFileDiff(rel=rel, error=f"(could not diff: {exc})"))
            diffs_shown += 1
            continue

        stdout = proc.stdout
        if stdout.startswith("Binary files "):
            results.append(ChangedFileDiff(rel=rel, binary_line=stdout.splitlines()[0]))
            diffs_shown += 1
            continue

        if proc.returncode not in (0, 1) and not stdout.strip():
            stderr_lines = proc.stderr.strip().splitlines()
            reason = stderr_lines[0] if stderr_lines else "unknown error"
            results.append(ChangedFileDiff(rel=rel, error=f"(diff failed: {reason})"))
            diffs_shown += 1
            continue

        lines = stdout.splitlines()[:max_lines_per_file]
        budget_left = max_total_lines - total_lines
        if len(lines) > budget_left:
            lines = lines[:budget_left]
        results.append(ChangedFileDiff(rel=rel, diff_lines=lines))
        diffs_shown += 1
        total_lines += len(lines)

    return ChangedDiffsResult(files=results, truncated=truncated, diff_unavailable=diff_unavailable)
