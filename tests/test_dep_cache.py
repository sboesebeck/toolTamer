"""Tests for the reverse-dependency cache (tui/core/dep_cache.py).

get_required_by() is one subprocess call per package and genuinely slow
(~1.3s per call for brew on a real machine — minutes for a few hundred
packages). The answer only changes when the set of installed packages
changes, so it's cached keyed on a fingerprint of that set.

Deliberately NOT replaced by a single bulk query: brew's bulk formula
data (brew info --json=v2 --installed) is formula-based, while
`brew uses --installed` is receipt-based — verified against all 396
formulae on a real machine, the bulk version reported 4 packages as
unused that are actually linked against by installed binaries
(icu4c@76 <- mailsy, icu4c@77 <- pass-otp, berkeley-db@5 <- perl,
unbound <- pass). That's the direction that breaks installs, so the
exact-but-slow call is kept and its result cached instead.
"""

from pathlib import Path

import pytest

from tui.core.dep_cache import ReverseDepCache, fingerprint


def test_fingerprint_is_stable_regardless_of_order():
    assert fingerprint(["git", "fzf", "vim"]) == fingerprint(["vim", "git", "fzf"])


def test_fingerprint_changes_when_a_package_is_added():
    before = fingerprint(["git", "fzf"])
    assert fingerprint(["git", "fzf", "vim"]) != before


def test_fingerprint_changes_when_a_package_is_removed():
    before = fingerprint(["git", "fzf", "vim"])
    assert fingerprint(["git", "fzf"]) != before


def test_fingerprint_ignores_duplicates_and_blanks():
    assert fingerprint(["git", "git", "", "  ", "fzf"]) == fingerprint(["git", "fzf"])


def test_fingerprint_matches_the_equivalent_shell_pipeline():
    """bin/tt checks cache validity without Python, via

        <list installed> | sed '/^$/d' | LC_ALL=C sort -u | shasum -a 256

    so the Python side has to hash exactly what that pipeline feeds in:
    sorted, deduped, newline-separated AND newline-terminated. The
    trailing newline is easy to get wrong and silently makes every
    bash-side cache check miss."""
    import hashlib
    import subprocess

    packages = ["fzf", "git", "python@3.12", "forketyfork/tap/clawtunes", "git"]

    shell = subprocess.run(
        "sed '/^$/d' | LC_ALL=C sort -u | shasum -a 256 | cut -d' ' -f1",
        input="\n".join(packages) + "\n",
        shell=True, capture_output=True, text=True,
    )

    assert fingerprint(packages) == shell.stdout.strip()


def test_get_returns_none_for_unknown_package(tmp_path: Path):
    cache = ReverseDepCache(tmp_path / "deps.tsv")
    assert cache.get("anything") is None


def test_put_then_get_roundtrips_in_memory(tmp_path: Path):
    cache = ReverseDepCache(tmp_path / "deps.tsv")
    cache.put("json-glib", ["rmlint"])
    cache.put("git", [])
    assert cache.get("json-glib") == ["rmlint"]
    assert cache.get("git") == []  # cached "nothing needs it", distinct from None


def test_save_then_load_roundtrips_through_the_file(tmp_path: Path):
    path = tmp_path / "deps.tsv"
    fp = fingerprint(["git", "json-glib"])
    writer = ReverseDepCache(path)
    writer.put("json-glib", ["rmlint", "other"])
    writer.put("git", [])
    writer.save(fp)

    reader = ReverseDepCache(path)
    reader.load(fp)
    assert reader.get("json-glib") == ["rmlint", "other"]
    assert reader.get("git") == []


def test_load_discards_everything_when_the_fingerprint_differs(tmp_path: Path):
    path = tmp_path / "deps.tsv"
    writer = ReverseDepCache(path)
    writer.put("json-glib", ["rmlint"])
    writer.save(fingerprint(["git", "json-glib"]))

    reader = ReverseDepCache(path)
    reader.load(fingerprint(["git", "json-glib", "newly-installed"]))

    assert reader.get("json-glib") is None  # stale — must be recomputed


def test_load_on_a_missing_file_is_a_no_op(tmp_path: Path):
    cache = ReverseDepCache(tmp_path / "does-not-exist.tsv")
    cache.load(fingerprint(["git"]))
    assert cache.get("git") is None


def test_load_survives_a_corrupt_file(tmp_path: Path):
    path = tmp_path / "deps.tsv"
    path.write_text("this is not\x00 a valid cache\nneither is this\n")
    cache = ReverseDepCache(path)
    cache.load(fingerprint(["git"]))  # must not raise
    assert cache.get("git") is None


def test_save_creates_missing_parent_directories(tmp_path: Path):
    path = tmp_path / "nested" / "dir" / "deps.tsv"
    cache = ReverseDepCache(path)
    cache.put("git", [])
    cache.save(fingerprint(["git"]))
    assert path.exists()


def test_save_failure_is_swallowed(tmp_path: Path, monkeypatch):
    """The cache is an optimization — a read-only or full disk must not
    take the whole screen down with it."""
    path = tmp_path / "deps.tsv"
    cache = ReverseDepCache(path)
    cache.put("git", [])

    def boom(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(Path, "write_text", boom)
    cache.save(fingerprint(["git"]))  # must not raise


def test_file_format_is_greppable_from_shell(tmp_path: Path):
    """bin/tt (bash, no jq dependency) reads this same cache, so the
    format has to stay one tab-separated record per line: the package
    name, a tab, then space-separated dependents."""
    path = tmp_path / "deps.tsv"
    cache = ReverseDepCache(path)
    cache.put("json-glib", ["rmlint", "other"])
    cache.put("git", [])
    cache.save(fingerprint(["git", "json-glib"]))

    lines = path.read_text().splitlines()
    assert lines[0].startswith("#")  # header/fingerprint is a comment line
    assert any(line.startswith("#") and "fingerprint" in line for line in lines)
    records = [l for l in lines if not l.startswith("#")]
    assert "json-glib\trmlint other" in records
    assert "git\t" in records  # known-empty is recorded, not omitted


def test_package_names_with_slashes_and_at_signs_roundtrip(tmp_path: Path):
    """Real brew names include taps (forketyfork/tap/clawtunes) and
    versions (python@3.12) — neither may break the line format."""
    path = tmp_path / "deps.tsv"
    cache = ReverseDepCache(path)
    cache.put("forketyfork/tap/clawtunes", ["python@3.12"])
    cache.put("python@3.12", [])
    cache.save(fingerprint(["forketyfork/tap/clawtunes", "python@3.12"]))

    reader = ReverseDepCache(path)
    reader.load(fingerprint(["forketyfork/tap/clawtunes", "python@3.12"]))
    assert reader.get("forketyfork/tap/clawtunes") == ["python@3.12"]
    assert reader.get("python@3.12") == []


def test_resolve_uses_cache_and_only_computes_misses(tmp_path: Path):
    """resolve() is the one entry point callers use: cached packages come
    back for free, only the misses hit the (slow) compute function."""
    cache = ReverseDepCache(tmp_path / "deps.tsv")
    cache.put("git", [])
    computed = []

    def compute(pkg):
        computed.append(pkg)
        return ["someone"] if pkg == "json-glib" else []

    result = cache.resolve(["git", "json-glib"], compute)

    assert result == {"git": [], "json-glib": ["someone"]}
    assert computed == ["json-glib"]  # "git" was served from the cache


def test_resolve_stores_the_computed_misses(tmp_path: Path):
    cache = ReverseDepCache(tmp_path / "deps.tsv")
    cache.resolve(["json-glib"], lambda pkg: ["rmlint"])
    assert cache.get("json-glib") == ["rmlint"]


def test_resolve_runs_misses_in_parallel(tmp_path: Path):
    """The whole point is that a cold cache stays bearable — the misses
    must overlap, not run one after another."""
    import threading
    import time

    cache = ReverseDepCache(tmp_path / "deps.tsv")
    lock = threading.Lock()
    in_flight = 0
    max_in_flight = 0

    def compute(pkg):
        nonlocal in_flight, max_in_flight
        with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        time.sleep(0.05)
        with lock:
            in_flight -= 1
        return []

    cache.resolve([f"pkg{i}" for i in range(10)], compute)

    assert max_in_flight > 1, "misses never overlapped — still sequential"


def test_resolve_reports_progress_for_misses_only(tmp_path: Path):
    cache = ReverseDepCache(tmp_path / "deps.tsv")
    cache.put("cached", [])
    seen = []

    cache.resolve(
        ["cached", "miss-a", "miss-b"],
        lambda pkg: [],
        progress=lambda done, total: seen.append((done, total)),
    )

    assert seen, "no progress reported"
    assert seen[-1] == (2, 2)  # only the two misses counted


def test_resolve_can_be_stopped_early(tmp_path: Path):
    import time

    cache = ReverseDepCache(tmp_path / "deps.tsv")
    done = []

    def compute(pkg):
        time.sleep(0.02)
        done.append(pkg)
        return []

    cache.resolve(
        [f"pkg{i}" for i in range(20)],
        compute,
        should_stop=lambda: len(done) >= 2,
    )

    assert len(done) < 20


def test_resolve_tolerates_a_failing_compute(tmp_path: Path):
    cache = ReverseDepCache(tmp_path / "deps.tsv")

    def compute(pkg):
        if pkg == "broken":
            raise RuntimeError("subprocess blew up")
        return ["user"]

    result = cache.resolve(["broken", "fine"], compute)

    assert result["fine"] == ["user"]
    assert result["broken"] == []
    # a failed lookup must NOT be cached as a confirmed "nothing needs it"
    assert cache.get("broken") is None
