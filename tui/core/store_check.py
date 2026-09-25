"""Warn about visible tracked files the store *git repo* cannot commit.

The store is a git repository and a *plain* tracked directory is stored as a
real tree, so any file literally named `.gitignore` inside one is read by git
as an ignore file for the store. A `.gitignore` that lists itself (opencode
does) is therefore ignored by the store git and never committed — while the
system copy stays visible to ToolTamer's own ignore engine. Every machine
then disagrees: the one that has the store copy sees it ignored, every other
one sees it missing and would delete the system copy on apply.

The tell-tale is a visible `.gitignore` (the only name git hijacks) that is
*not carried by the store git* — either absent from the store working tree or
present but untracked. That state is what diverges between machines.

Only plain mirrored directories are affected. A repo entry (`.ttgit`) is
cloned via git and never stores its contents, so it is skipped — its
`.gitignore` is the repository's own business.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tui.core.config import TTConfig, _resolve_effective_target, iter_tree_files
from tui.core.ignore import load

IGNORE_NAME = ".gitignore"


def _git_tracked(base: Path, rel_paths: list[str]) -> set[str] | None:
    """Subset of `rel_paths` (relative to `base`) tracked by the store git.

    None when git is unavailable or `base` is not a repo, so callers can skip
    rather than misreport every file."""
    if not rel_paths:
        return set()
    if not (base / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(base), "ls-files", "--cached", "--", *rel_paths],
            capture_output=True, text=True,
        )
    except (FileNotFoundError, OSError):
        return None
    if proc.returncode not in (0,):
        return None
    return {ln.strip() for ln in proc.stdout.splitlines() if ln.strip()}


def store_ignored_in_dir(
    cfg: TTConfig, config: str, stored: str, target: str, home: Path | None = None
) -> list[str]:
    """Visible `.gitignore` files under one plain tracked directory that the
    store git does not carry (missing or untracked), so they never reach
    another machine. Returns rel paths."""
    home = home or Path.home()
    store_dir = cfg.configs_dir / config / "files" / stored
    if not store_dir.is_dir():
        return []
    sys_dir = home / _resolve_effective_target(stored, target)
    if not sys_dir.is_dir():
        return []
    matcher = load(sys_dir)
    visible = [
        rel for rel, p in iter_tree_files(sys_dir, matcher)
        if p.is_file() and not p.is_symlink() and p.name == IGNORE_NAME
    ]
    if not visible:
        return []
    prefix = f"configs/{config}/files/{stored}/"
    tracked = _git_tracked(cfg.base, [prefix + rel for rel in visible])
    if tracked is None:
        # No store git to ask — fall back to "missing on disk means not carried".
        return [rel for rel in visible if not (store_dir / rel).exists()]
    return [rel for rel in visible if prefix + rel not in tracked]


def store_ignored_files(
    cfg: TTConfig, host: str, home: Path | None = None
) -> list[tuple[str, str, str]]:
    """(config, stored, rel) across all effective *plain* directory mappings."""
    home = home or Path.home()
    out: list[tuple[str, str, str]] = []
    for mapping in cfg.get_effective_file_mappings(host):
        if not mapping.is_effective or mapping.is_repo or not mapping.repo_path.is_dir():
            continue
        for rel in store_ignored_in_dir(
            cfg, mapping.config, mapping.stored, mapping.target, home
        ):
            out.append((mapping.config, mapping.stored, rel))
    return out
