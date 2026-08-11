"""On-disk cache for reverse-dependency lookups.

SystemInfo.get_required_by() is one subprocess call per package and
genuinely slow (measured ~1.3s per `brew uses --installed` call), which
makes a few hundred packages take minutes — too slow for the package
screen, the dashboard, and especially a sync run.

The answer only changes when the set of installed packages changes, so
results are cached keyed on a fingerprint of that set. Install or remove
anything and the whole cache is rebuilt; otherwise lookups are free.
Merely listing a package in a config does NOT affect this — that changes
whether a package counts as "tracked", not what depends on it.

Why not one bulk query instead: brew does offer the whole graph at once
(`brew info --json=v2 --installed`, ~2s vs ~75s), but it is formula-based
while `brew uses --installed` is receipt-based, i.e. what the installed
binaries are actually linked against. Verified against all 396 formulae
on a real machine, the bulk version reported 4 packages as unused that
are genuinely required (icu4c@76 <- mailsy, icu4c@77 <- pass-otp,
berkeley-db@5 <- perl, unbound <- pass), because those consumers were
built against a version the current formula no longer declares. Reporting
a needed package as removable is the direction that breaks installs, so
the exact call is kept and its result cached instead.

File format — deliberately line-based TSV rather than JSON so bin/tt
(bash, and we don't want a jq dependency) can read the same cache with
grep/cut:

    # tooltamer reverse-dependency cache v1
    # fingerprint <sha256 hex>
    json-glib\trmlint other
    git\t

A package with no dependents is recorded with an empty field — that's a
cached "nothing needs this", which is different from "not looked up yet"
(absent from the file entirely).
"""

import concurrent.futures
import hashlib
from pathlib import Path

CACHE_VERSION = "1"
_HEADER = f"# tooltamer reverse-dependency cache v{CACHE_VERSION}"


def fingerprint(installed: list[str]) -> str:
    """Stable identity of an installed-package set. Order-independent and
    blank/duplicate-tolerant, so it only changes when packages actually
    come or go.

    Defined to match what a shell pipeline naturally produces, so bin/tt
    can check cache validity without Python:

        brew list -1 | sed '/^$/d' | LC_ALL=C sort -u | shasum -a 256

    i.e. newline-SEPARATED *and* newline-TERMINATED (the trailing newline
    matters — without it the two disagree), and sorted bytewise, which is
    what LC_ALL=C gives and what Python's sorted() does anyway."""
    names = sorted({n.strip() for n in installed if n and n.strip()})
    if not names:
        return hashlib.sha256(b"").hexdigest()
    payload = "\n".join(names) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ReverseDepCache:
    """Package name -> list of installed packages requiring it.

    Never raises for I/O reasons: this is an optimization, and a
    read-only config dir or a corrupt file must degrade to "no cache",
    not take down the screen using it.
    """

    def __init__(self, path: Path):
        self._path = Path(path)
        self._entries: dict[str, list[str]] = {}

    def load(self, expected_fingerprint: str) -> None:
        """Populate from disk, but only if the file was written for the
        same installed-package set. Anything else (missing, corrupt,
        stale, wrong version) leaves the cache empty."""
        try:
            raw = self._path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return

        entries: dict[str, list[str]] = {}
        seen_fingerprint = None
        version_ok = False
        for line in raw.splitlines():
            if line.startswith("#"):
                if line.startswith(_HEADER):
                    version_ok = True
                elif line.startswith("# fingerprint "):
                    seen_fingerprint = line[len("# fingerprint "):].strip()
                continue
            if "\t" not in line:
                continue  # not a record — ignore rather than fail
            pkg, _, users = line.partition("\t")
            if pkg:
                entries[pkg] = users.split()

        if version_ok and seen_fingerprint == expected_fingerprint:
            self._entries = entries

    def save(self, current_fingerprint: str) -> None:
        lines = [_HEADER, f"# fingerprint {current_fingerprint}"]
        for pkg in sorted(self._entries):
            lines.append(f"{pkg}\t{' '.join(self._entries[pkg])}")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass  # cache is optional — never fail the caller over it

    def get(self, package: str) -> list[str] | None:
        """Cached dependents, [] for a cached "nothing needs it", or None
        if this package hasn't been looked up yet."""
        return self._entries.get(package)

    def put(self, package: str, users: list[str]) -> None:
        self._entries[package] = list(users)

    def resolve(
        self,
        packages: list[str],
        compute,
        progress=None,
        should_stop=None,
    ) -> dict[str, list[str]]:
        """Reverse-dependency lists for `packages`, served from the cache
        where possible and computed (in parallel) only for the misses.

        compute: callable(package) -> list[str], the expensive lookup.
        progress: optional callable(done, total) over the misses only.
        should_stop: optional zero-arg callable; when it returns True,
            remaining not-yet-started lookups are abandoned.

        A compute() that raises yields [] for that package for this call
        but is NOT cached — a failed lookup must never be remembered as a
        confirmed "nothing needs it", which would be the unsafe direction.
        """
        result: dict[str, list[str]] = {}
        misses: list[str] = []
        for pkg in packages:
            cached = self.get(pkg)
            if cached is None:
                misses.append(pkg)
            else:
                result[pkg] = cached

        if not misses:
            return result

        done = 0
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=8)
        try:
            futures = {pool.submit(compute, pkg): pkg for pkg in misses}
            for future in concurrent.futures.as_completed(futures):
                pkg = futures[future]
                try:
                    users = future.result()
                    self.put(pkg, users)
                except Exception:
                    users = []  # not cached — see docstring
                result[pkg] = users
                done += 1
                if progress:
                    progress(done, len(misses))
                if should_stop is not None and should_stop():
                    break
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        return result


def default_cache_path(base: Path) -> Path:
    """Where the cache lives for a given ToolTamer base dir. Kept inside
    the base (not XDG_CACHE_HOME) so bin/tt, which already resolves
    $BASE, can find the same file without extra path logic."""
    return Path(base) / "cache" / "reverse-deps.tsv"


class DependencyResolver:
    """What callers actually use: reverse-dependency lookups backed by
    the on-disk cache, with fingerprint handling built in.

    The installed-package list is passed in rather than fetched here —
    every caller already has it (it's what tells them which packages to
    ask about in the first place), and it's one subprocess call we don't
    want to make twice.
    """

    def __init__(self, system, cache_path: Path):
        self._system = system
        self._cache = ReverseDepCache(cache_path)
        self._path = Path(cache_path)
        self._loaded_fingerprint: str | None = None

    def _sync(self, installed: list[str]) -> str:
        """Make sure the in-memory cache matches the current installed
        set, reloading from disk when the set changed (or on first use)."""
        current = fingerprint(installed)
        if self._loaded_fingerprint != current:
            self._cache = ReverseDepCache(self._path)
            self._cache.load(current)
            self._loaded_fingerprint = current
        return current

    def resolve(
        self,
        packages: list[str],
        installed: list[str],
        progress=None,
        should_stop=None,
    ) -> dict[str, list[str]]:
        current = self._sync(installed)
        result = self._cache.resolve(
            packages,
            self._system.get_required_by,
            progress=progress,
            should_stop=should_stop,
        )
        self._cache.save(current)
        return result

    def required_by(self, package: str, installed: list[str]) -> list[str]:
        """Single-package lookup — same cache, same invalidation."""
        return self.resolve([package], installed).get(package, [])

    def invalidate(self) -> None:
        """Drop everything, in memory and on disk. For an explicit
        "rescan" action; normal invalidation happens by itself via the
        fingerprint."""
        self._cache = ReverseDepCache(self._path)
        self._loaded_fingerprint = None
        try:
            self._path.unlink()
        except OSError:
            pass
