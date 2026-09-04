"""Audit and fix package names that need a tap qualifier.

A package from a third-party tap only installs on a machine where that
tap is already tapped. `brew install clawtunes` fails on a fresh
machine — the short name means nothing until the tap exists. The fully
qualified form, `brew install forketyfork/tap/clawtunes`, works
everywhere: brew taps automatically when given one.

So packages from third-party taps belong in to_install.brew fully
qualified. This finds config entries that aren't and rewrites them, which
is what makes them installable on a new host.

Scoped to the current host's resolved config chain and to packages that
are actually installed here — a package's tap can only be read off an
installed package, so entries for anything not installed are left alone
rather than guessed at (run this on the host that has them).

Usage:
    python -m tui.fix_taps                # dry run — list what would change
    python -m tui.fix_taps --apply        # rewrite, with confirmation
    python -m tui.fix_taps --apply --yes  # rewrite without the prompt
"""

import argparse
import sys

from tui.core.config import TTConfig
from tui.core.pkg_names import installed_index, is_installed
from tui.core.system import SystemInfo, default_base


def find_short_tap_names(
    tt_config: TTConfig, system: SystemInfo
) -> list[tuple[str, str, str]]:
    """(config, short_name, fully_qualified_name) for every entry in the
    current host's config chain that names a third-party-tap package by
    its short name only."""
    full_names = system.list_package_full_names()
    if not full_names:
        return []
    installed_idx = installed_index(system.list_installed_packages())

    found: list[tuple[str, str, str]] = []
    for cfg in tt_config.resolve_chain(system.hostname):
        for pkg in sorted(tt_config.get_packages(cfg, system.installer)):
            if "/" in pkg:
                continue  # already qualified
            if not is_installed(pkg, installed_idx):
                continue  # can't determine its tap from here
            full = full_names.get(pkg)
            if full:
                found.append((cfg, pkg, full))
    return found


def _rewrite(tt_config: TTConfig, config: str, installer: str, old: str, new: str) -> None:
    """Replace a package entry in place, preserving position, comments and
    everything else in the file."""
    pkg_file = tt_config.configs_dir / config / f"to_install.{installer}"
    if not pkg_file.exists():
        return
    lines = pkg_file.read_text().splitlines()
    changed = [new if line.strip() == old else line for line in lines]
    pkg_file.write_text("\n".join(changed) + "\n" if changed else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tt-fix-taps",
        description=(
            "Rewrite third-party-tap packages in to_install.* to their "
            "fully qualified names, so they install on a fresh machine "
            "without the tap being added first. Dry-run by default."
        ),
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="actually rewrite the entries (default: dry-run, list only)",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="skip the confirmation prompt when --apply is given",
    )
    args = parser.parse_args(argv)

    base = default_base()
    tt_config = TTConfig(base)
    system = SystemInfo(base)

    found = find_short_tap_names(tt_config, system)
    if not found:
        print("All tap packages in this host's configs are fully qualified.")
        return 0

    print(
        f"{len(found)} package(s) come from a third-party tap but are "
        "listed by short name only:\n"
    )
    for cfg, short, full in found:
        print(f"  {short}  ({cfg})  ->  {full}")
    print(
        "\nWithout the qualifier these fail to install on a machine where "
        "the tap isn't set up yet."
    )

    if not args.apply:
        print("\nDry run — nothing changed. Re-run with --apply to rewrite these.")
        return 0

    if not args.yes:
        answer = input(f"\nRewrite all {len(found)} entry/entries? [y/N] ")
        if answer.strip().lower() != "y":
            print("Aborted, nothing changed.")
            return 1

    for cfg, short, full in found:
        _rewrite(tt_config, cfg, system.installer, short, full)
        print(f"{cfg}: {short} -> {full}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
