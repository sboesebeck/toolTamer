"""Fill the reverse-dependency cache with what a sync run needs.

bin/tt's syncInstall() calls depCount() for every installed package the
resolved config chain does not list — on a real machine that is a couple
of hundred packages — and each miss costs one `brew uses --installed`
(~1.3s), serially. The cache exists for exactly this, but nothing ever
populated it with that set: the TUI only resolves the extras it shows
(packages.py deliberately skips everything list_dependency_packages()
already flagged), and tt-cleanup-deps only resolves *tracked* packages.
So the sync's several hundred lookups stayed permanent cache misses and
every run paid the full serial price again.

This tool resolves the sync's candidate set through the same
DependencyResolver, which runs misses in parallel (8 workers) and writes
the shared $BASE/cache/reverse-deps.tsv. bin/tt then reads it with
grep/awk as before. Cold that is ~35s instead of ~5min; warm it is free
until a package is actually installed or removed.

bin/tt passes the candidate and installed lists it already computed
rather than letting this re-derive them: the fingerprint the bash side
checks the cache against comes from *its* list, and a list derived twice
can disagree (a package installed between the two calls, a differently
filtered config chain), which would invalidate the whole warm-up.

Usage:
    python -m tui.warm_deps                        # derive candidates from the config
    python -m tui.warm_deps --candidates FILE      # ... or take them from a file
    python -m tui.warm_deps --candidates FILE --installed FILE
"""

import argparse
import sys
from pathlib import Path

from tui.core.config import TTConfig
from tui.core.dep_cache import DependencyResolver, default_cache_path
from tui.core.pkg_names import short_name
from tui.core.system import SystemInfo, default_base


def _read_candidates(path: Path) -> list[str]:
    """Package names from a one-per-line file, applying the same filter
    bin/tt's sync loop uses (blank lines, comments, and `key=value`
    lines are not packages)."""
    names: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or "#" in entry or "=" in entry:
            continue
        names.append(entry)
    return names


def _read_installed(path: Path) -> list[str]:
    """The installed-package list, filtered exactly like the fingerprint
    definition (blank lines only — see dep_cache.fingerprint and the
    matching shell pipeline in bin/include.sh's loadDepCache).

    Deliberately NOT the candidate filter above: dropping a line here
    that the bash side counts would produce a fingerprint it doesn't
    recognize, and the warm-up would be discarded as stale."""
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def candidates_from_config(
    tt_config: TTConfig, system: SystemInfo, installed: list[str]
) -> list[str]:
    """Installed packages that no config in the host's chain lists —
    the set syncInstall() runs the reverse-dependency check on.

    Config entries may be tap-qualified (forketyfork/tap/clawtunes) while
    the package manager lists the short name, so compare on the short
    form (see tui/core/pkg_names.py) — otherwise every tap package looks
    untracked and gets a lookup the sync never asks for."""
    tracked: set[str] = set()
    for cfg in tt_config.resolve_chain(system.hostname):
        for pkg in tt_config.get_packages(cfg, system.installer):
            tracked.add(short_name(pkg))
    return sorted({p for p in installed if short_name(p) not in tracked})


def main(
    argv: list[str] | None = None,
    tt_config: TTConfig | None = None,
    system: SystemInfo | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="tt-warm-deps",
        description=(
            "Pre-compute the reverse-dependency lookups a sync run needs "
            "and store them in the shared cache, in parallel, so bin/tt "
            "doesn't do them one at a time."
        ),
    )
    parser.add_argument(
        "--candidates", metavar="FILE",
        help="file with one package name per line to resolve (default: "
        "every installed package the host's config chain doesn't list)",
    )
    parser.add_argument(
        "--installed", metavar="FILE",
        help="file with the installed package list the cache should be "
        "keyed on (default: ask the package manager)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="no progress output even on a terminal",
    )
    args = parser.parse_args(argv)

    base = default_base()
    if tt_config is None:
        tt_config = TTConfig(base)
    if system is None:
        system = SystemInfo(base)

    try:
        if args.installed:
            installed = _read_installed(Path(args.installed))
        else:
            installed = system.list_installed_packages()
        candidates = (
            _read_candidates(Path(args.candidates)) if args.candidates
            else candidates_from_config(tt_config, system, installed)
        )
    except OSError as exc:
        print(f"tt-warm-deps: {exc}", file=sys.stderr)
        return 1

    if not installed or not candidates:
        return 0

    show_progress = sys.stdout.isatty() and not args.quiet

    def progress(done: int, total: int) -> None:
        if show_progress:
            print(f"\rResolving dependencies... {done}/{total}", end="", flush=True)

    resolver = DependencyResolver(system, default_cache_path(tt_config.base))
    resolver.resolve(candidates, installed=installed, progress=progress)
    if show_progress:
        print("\r\033[K", end="", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
