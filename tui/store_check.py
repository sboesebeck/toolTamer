"""CLI: report visible tracked files the store git repo refuses to commit.

Used by `tt` at sync time (a warning) and available as `tt --check-files`.
Exit code 1 when something was found, so it can gate a script; the message
explains that a `.gitignore` inside a tracked directory is read by the store
git as an ignore file and thus never leaves this machine.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path

from tui.core.machine_id import read_machine_id
from tui.core.store_check import store_ignored_files


def _default_base() -> Path:
    env = os.environ.get("TT_BASE")
    return Path(env) if env else Path.home() / ".config" / "toolTamer"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tui.store_check")
    parser.add_argument("--base", type=Path, default=None, help="override TT_BASE")
    args = parser.parse_args(argv)

    from tui.core.config import TTConfig

    base = args.base or _default_base()
    machine_id = read_machine_id(base) or socket.gethostname()
    hits = store_ignored_files(TTConfig(base), machine_id)
    if not hits:
        return 0
    print("WARNING: the store git repo ignores these visible tracked files.")
    print("They stay only on this machine and read as changed/deleted elsewhere:")
    for config, stored, rel in hits:
        print(f"  {config}:{stored}/{rel}")
    print("A file named .gitignore inside a tracked directory is read by the store")
    print("git as an ignore file; if it lists itself it is never committed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
