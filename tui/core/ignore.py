"""Ignore rules for tracked directories (.gitignore / .ttignore).

A tracked directory is normally mirrored wholesale. Ignore files inside it
carve out a *visible set*: everything that is not hidden by a rule. All
operations that look at the tree (snapshot, mirror, hash, diff, extra
detection) work on that visible set, so ignored entries are invisible to
ToolTamer in both directions — never stored, never written, never deleted,
never hashed.

The matcher follows real gitignore semantics via `pathspec.GitIgnoreSpec`
(anchors, `**`, `!` negation, `dir/`, nested ignore files). `.gitignore` and
`.ttignore` are additive, in that order, so a later `.ttignore` pattern wins
over an earlier `.gitignore` one. Deeper directories win over shallower ones.

This module has no Textual dependency: the TUI uses it directly, and
`tui/ttignore.py` exposes it as a CLI for the Bash mirror. There is exactly
one implementation of the matching semantics.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pathspec

IGNORE_FILENAMES = (".gitignore", ".ttignore")


class IgnoreMatcher:
    """Applies the ignore files under `rules_root` to paths relative to it.

    Specs are loaded lazily per directory and cached, so a matcher over a
    large tree reads each ignore file at most once."""

    def __init__(self, rules_root: Path):
        self.rules_root = Path(rules_root)
        self._specs: dict[str, pathspec.GitIgnoreSpec | None] = {}

    def _dir_spec(self, rel_dir: str) -> pathspec.GitIgnoreSpec | None:
        """The combined spec for the ignore files directly in rel_dir.

        `.gitignore` first, then `.ttignore`: both are concatenated into a
        single spec so a later `.ttignore` rule can re-include (`!`) what an
        earlier `.gitignore` rule ignored. None when the directory holds no
        ignore file at all."""
        if rel_dir in self._specs:
            return self._specs[rel_dir]
        directory = self.rules_root / rel_dir if rel_dir else self.rules_root
        lines: list[str] = []
        found = False
        for name in IGNORE_FILENAMES:
            f = directory / name
            try:
                if f.is_file():
                    lines.extend(f.read_text(errors="replace").splitlines())
                    found = True
            except OSError:
                # An unreadable ignore file must still count as present, so
                # the caller does not fall back to "no rules" and mirror
                # everything.
                found = True
        spec = pathspec.GitIgnoreSpec.from_lines(lines) if found else None
        self._specs[rel_dir] = spec
        return spec

    def is_ignored(self, rel: str, is_dir: bool = False) -> bool:
        """True when `rel` (relative to rules_root) is hidden by a rule.

        A path cannot be re-included once a parent directory is excluded
        (gitignore's rule), which is also what makes a filter run over every
        file agree with a pruned walk: the pruned walk never looks inside an
        excluded directory, so no nested rule there may re-add anything."""
        rel = rel.replace(os.sep, "/").strip("/")
        if not rel:
            return False
        parts = rel.split("/")
        for i in range(1, len(parts)):
            if self._is_ignored_self("/".join(parts[:i]), is_dir=True):
                return True
        return self._is_ignored_self(rel, is_dir)

    def _is_ignored_self(self, rel: str, is_dir: bool) -> bool:
        """Apply every ancestor directory's spec from the root down; the last
        level with a matching rule decides. `res.index is None` means no rule
        matched at that level, so the decision from a shallower level
        stands."""
        parts = rel.split("/")
        ancestors = [""] + ["/".join(parts[:i]) for i in range(1, len(parts))]
        ignored = False
        for depth in ancestors:
            spec = self._dir_spec(depth)
            if spec is None:
                continue
            sub = rel if not depth else rel[len(depth) + 1:]
            # A pattern like `build/` only matches the directory itself when
            # the tested path carries the trailing slash; without it, the
            # directory passes but its children are still ignored.
            key = f"{sub}/" if is_dir else sub
            res = spec.check_file(key)
            if res.index is not None:
                ignored = res.include
        return ignored


def load(rules_root: Path) -> IgnoreMatcher | None:
    """Build a matcher for `rules_root`, or None when the tree holds no
    `.gitignore`/`.ttignore` anywhere.

    None is the zero-cost fast path: every caller then behaves exactly as it
    did before ignore support existed (no rules, no engine work)."""
    rules_root = Path(rules_root)
    if not rules_root.is_dir():
        return None
    for _dirpath, _dirnames, filenames in os.walk(rules_root, followlinks=False):
        if any(name in filenames for name in IGNORE_FILENAMES):
            return IgnoreMatcher(rules_root)
    return None


def iter_visible(
    walk_root: Path, matcher: IgnoreMatcher | None, onerror=None
) -> Iterator[tuple[str, Path]]:
    """Yield (relative_posix_path, path) for the visible files and symlinks
    under walk_root. Ignored directories are pruned, so an ignored,
    unreadable directory never blocks a walk.

    Same contract as `config.iter_tree_files`, with the matcher applied.
    `onerror` is forwarded to os.walk, exactly as dir_fully_readable uses it
    to notice a scandir failure the walk would otherwise hide."""
    walk_root = Path(walk_root)
    for dirpath, dirnames, filenames in os.walk(
        walk_root, followlinks=False, onerror=onerror
    ):
        base = Path(dirpath)
        for name in filenames:
            p = base / name
            rel = p.relative_to(walk_root).as_posix()
            if matcher is not None and matcher.is_ignored(rel, is_dir=False):
                continue
            yield rel, p
        for name in list(dirnames):
            p = base / name
            rel = p.relative_to(walk_root).as_posix()
            if p.is_symlink():
                dirnames.remove(name)
                if matcher is not None and matcher.is_ignored(rel, is_dir=False):
                    continue
                yield rel, p
            elif matcher is not None and matcher.is_ignored(rel, is_dir=True):
                dirnames.remove(name)


def append_ignore(rules_root: Path, rel: str, is_dir: bool) -> None:
    """Append an anchored `/<rel>` (or `/<rel>/`) line to root/.ttignore.

    The leading slash anchors the pattern to the tracked root, so ignoring
    `/secrets/token.json` cannot accidentally match a same-named file
    elsewhere. Idempotent: an already-present line is left alone."""
    rules_root = Path(rules_root)
    rel = rel.replace(os.sep, "/").strip("/")
    if not rel:
        return
    line = f"/{rel}/" if is_dir else f"/{rel}"
    f = rules_root / ".ttignore"
    existing = ""
    if f.exists():
        try:
            existing = f.read_text()
        except OSError:
            existing = ""
    if any(ln.strip() == line for ln in existing.splitlines()):
        return
    rules_root.mkdir(parents=True, exist_ok=True)
    prefix = "" if (not existing or existing.endswith("\n")) else "\n"
    with f.open("a") as fh:
        fh.write(f"{prefix}{line}\n")
