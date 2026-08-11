"""One-off cleanup: remove packages from to_install.* files that are only
tracked there because an old syncInstall() bug (fixed in bin/tt — see
bin/include.sh's $USES and bin/tt's syncInstall()) used to persist every
detected dependency into the current host's config, permanently, instead
of just skipping its removal for that run.

Scoped to the CURRENT host's resolved config chain (common + includes +
the host itself) only: get_required_by() needs real installed-package
data from the package manager, which is only trustworthy for packages
actually installed on the machine running this script. Other hosts'
configs need this run on their own machine.

"Required by something" alone doesn't prove an entry is redundant — a
package can be explicitly wanted *and* happen to be a dependency of
something else too (e.g. python3). So this never deletes anything by
itself: it lists candidates with their reason and asks for confirmation
before touching any config file.

Usage:
    python -m tui.cleanup_deps              # dry run — list candidates only
    python -m tui.cleanup_deps --apply       # list, then confirm, then remove
    python -m tui.cleanup_deps --apply --yes # remove without the prompt
    python -m tui.cleanup_deps --apply --keep git --keep fzf
    python -m tui.cleanup_deps --fast        # skip the slow per-package check
"""

import argparse
import os
import sys
from pathlib import Path

from tui.core.config import TTConfig
from tui.core.dep_cache import DependencyResolver, default_cache_path
from tui.core.system import SystemInfo


def find_candidates(
    tt_config: TTConfig,
    system: SystemInfo,
    fast: bool = False,
    progress=None,
    resolver=None,
) -> list[tuple[str, str, list[str]]]:
    """Packages in the current host's resolved config chain that are
    installed and look like dependencies rather than things explicitly
    wanted. Returns (config, package, reason) tuples in a stable order —
    cheap-signal hits (in chain order) first, then expensive-check hits
    (in chain order) — one per config a candidate is listed in, since a
    package can legitimately appear in more than one config.

    Two-tier check, in order of cost:
      1. list_dependency_packages() — one subprocess call for the WHOLE
         set (install *reason*: apt-mark auto vs. manual / brew's
         --no-installed-on-request). Catches the vast majority of stray
         dependency entries essentially for free.
      2. get_required_by() — one subprocess call PER remaining package
         (structural: currently required by another installed package),
         via DependencyResolver so results are cached on disk and any
         misses run in parallel. Catches what (1) misses (the json-glib
         report). On a cold cache this is still the slow part on a config
         with hundreds of packages (hence the progress callback); after
         that it's free until something is installed or removed.
         fast=True skips this tier entirely.

    progress: optional callable(done, total) invoked as tier 2's
    lookups complete, so a caller can show progress instead of the
    command looking hung on a cold cache."""
    installed_list = system.list_installed_packages()
    installed = set(installed_list)
    dep_only = set(system.list_dependency_packages())

    chain_pkgs: list[tuple[str, str]] = []
    for cfg in tt_config.resolve_chain(system.hostname):
        for pkg in sorted(tt_config.get_packages(cfg, system.installer)):
            if pkg in installed:
                chain_pkgs.append((cfg, pkg))

    candidates: list[tuple[str, str, list[str]]] = []
    to_check: list[tuple[str, str]] = []
    for cfg, pkg in chain_pkgs:
        if pkg in dep_only:
            candidates.append((cfg, pkg, ["installed as a dependency"]))
        else:
            to_check.append((cfg, pkg))

    if not fast and to_check:
        if resolver is None:
            resolver = DependencyResolver(
                system, default_cache_path(tt_config.base)
            )
        resolved = resolver.resolve(
            sorted({pkg for _, pkg in to_check}),
            installed=installed_list,
            progress=progress,
        )
        for cfg, pkg in to_check:
            required_by = resolved.get(pkg, [])
            if required_by:
                candidates.append((cfg, pkg, required_by))

    return candidates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tt-cleanup-deps",
        description=(
            "One-off cleanup: remove packages from to_install.* that are "
            "only tracked because an old sync bug persisted detected "
            "dependencies into the config. Dry-run by default."
        ),
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="actually remove the candidates (default: dry-run, list only)",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="skip the confirmation prompt when --apply is given",
    )
    parser.add_argument(
        "--keep", action="append", default=[], metavar="PACKAGE",
        help="never remove this package, even if it looks like a "
        "dependency (repeatable)",
    )
    parser.add_argument(
        "--fast", action="store_true",
        help="skip the slow per-package reverse-dependency check (only "
        "the cheap, whole-set install-reason signal) — near-instant, "
        "but misses cases the cheap signal alone gets wrong (see "
        "get_required_by in tui/core/system.py)",
    )
    parser.add_argument(
        "--rescan", action="store_true",
        help="discard the cached reverse-dependency data and look "
        "everything up again (the cache normally invalidates itself when "
        "packages are installed or removed)",
    )
    args = parser.parse_args(argv)

    base = Path(os.environ.get("TT_BASE", str(Path.home() / ".config" / "toolTamer")))
    tt_config = TTConfig(base)
    system = SystemInfo()
    resolver = DependencyResolver(system, default_cache_path(base))
    if args.rescan:
        resolver.invalidate()

    # \r-based progress only makes sense on a terminal — piped or
    # redirected it turns into one line per package.
    interactive = sys.stdout.isatty()

    def progress(done: int, total: int) -> None:
        if interactive:
            print(f"\rChecking packages... {done}/{total}", end="", flush=True)

    candidates = find_candidates(
        tt_config, system, fast=args.fast,
        progress=None if args.fast else progress,
        resolver=resolver,
    )
    if not args.fast and interactive:
        print()  # newline after the progress line, if any was printed

    candidates = [c for c in candidates if c[1] not in args.keep]

    if not candidates:
        print("No dependency-only packages found in this host's configs.")
        return 0

    print(
        f"{len(candidates)} package(s) look like they're only tracked "
        "because they're a dependency:\n"
    )
    for cfg, pkg, required_by in candidates:
        print(f"  {pkg} ({cfg}) — required by: {', '.join(required_by)}")

    if not args.apply:
        print("\nDry run — nothing changed. Re-run with --apply to remove these.")
        return 0

    if not args.yes:
        answer = input(
            f"\nRemove all {len(candidates)} listed package(s) from their "
            "configs? [y/N] "
        )
        if answer.strip().lower() != "y":
            print("Aborted, nothing changed.")
            return 1

    for cfg, pkg, _ in candidates:
        tt_config._remove_package(cfg, pkg, system.installer)
        print(f"Removed {pkg} from {cfg}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
