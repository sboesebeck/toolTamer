"""CLI wrapper around the ignore engine, for the Bash mirror.

Bash must never grow a second matcher: it collects candidate paths with
`find` and pipes them through this module, so the visible set is computed
by the same `tui/core/ignore.py` code the TUI uses.

Usage:
    python -m tui.ttignore filter <rules_root>          # stdin: rel paths -> stdout: visible
    python -m tui.ttignore check-readable <tree> <rules_root>

`filter` is one command for both mirror sides: the source side is filtered
with its own rules, the destination side with the same rules (it can live in
a different tree). `check-readable` mirrors dir_fully_readable and exits 1
when a non-ignored entry cannot be enumerated.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tui.core.ignore import load


def _visible(rules_root: Path):
    """Return a predicate, or None when the tree has no ignore files."""
    matcher = load(rules_root)
    if matcher is None:
        return None

    def _keep(rel: str) -> bool:
        return not matcher.is_ignored(rel, is_dir=False)

    return _keep


def _cmd_filter(rules_root: Path) -> int:
    keep = _visible(rules_root)
    out = sys.stdout
    for raw in sys.stdin:
        rel = raw.strip()
        if rel.startswith("./"):
            rel = rel[2:]
        if not rel:
            continue
        if keep is None or keep(rel):
            out.write(rel + "\n")
    return 0


def _cmd_check_readable(tree: Path, rules_root: Path) -> int:
    from tui.core.config import dir_fully_readable

    matcher = load(rules_root)
    return 0 if dir_fully_readable(tree, matcher) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tui.ttignore")
    sub = parser.add_subparsers(dest="command", required=True)

    p_filter = sub.add_parser("filter", help="filter rel paths from stdin")
    p_filter.add_argument("rules_root", type=Path)

    p_check = sub.add_parser("check-readable", help="exit 1 if a visible entry is unreadable")
    p_check.add_argument("tree", type=Path)
    p_check.add_argument("rules_root", type=Path)

    args = parser.parse_args(argv)
    if args.command == "filter":
        return _cmd_filter(args.rules_root)
    if args.command == "check-readable":
        return _cmd_check_readable(args.tree, args.rules_root)
    return 2


if __name__ == "__main__":
    sys.exit(main())
