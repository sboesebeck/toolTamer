"""Tests for DependencyResolver — the façade the screens use, wiring
SystemInfo.get_required_by() together with the on-disk ReverseDepCache
(fingerprint handling, load-on-first-use, save-after-compute).
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tui.core.dep_cache import DependencyResolver, ReverseDepCache, fingerprint


class _FakeSystem:
    def __init__(self, mapping: dict[str, list[str]]):
        self._mapping = mapping
        self.calls: list[str] = []

    def get_required_by(self, package: str) -> list[str]:
        self.calls.append(package)
        return self._mapping.get(package, [])


@pytest.fixture
def cache_path(tmp_path: Path) -> Path:
    return tmp_path / "cache" / "reverse-deps.tsv"


def test_resolve_computes_on_a_cold_cache(cache_path: Path):
    system = _FakeSystem({"json-glib": ["rmlint"]})
    resolver = DependencyResolver(system, cache_path)

    result = resolver.resolve(["json-glib", "git"], installed=["json-glib", "git"])

    assert result == {"json-glib": ["rmlint"], "git": []}
    assert sorted(system.calls) == ["git", "json-glib"]


def test_resolve_persists_so_a_second_process_needs_no_calls(cache_path: Path):
    installed = ["json-glib", "git"]
    first = DependencyResolver(_FakeSystem({"json-glib": ["rmlint"]}), cache_path)
    first.resolve(["json-glib", "git"], installed=installed)

    # fresh resolver == a later run of the TUI / cleanup script / sync
    system2 = _FakeSystem({"json-glib": ["rmlint"]})
    second = DependencyResolver(system2, cache_path)
    result = second.resolve(["json-glib", "git"], installed=installed)

    assert result == {"json-glib": ["rmlint"], "git": []}
    assert system2.calls == []  # entirely served from disk


def test_installing_a_package_invalidates_the_whole_cache(cache_path: Path):
    first = DependencyResolver(_FakeSystem({"json-glib": ["rmlint"]}), cache_path)
    first.resolve(["json-glib"], installed=["json-glib", "git"])

    system2 = _FakeSystem({"json-glib": ["rmlint", "newtool"]})
    second = DependencyResolver(system2, cache_path)
    result = second.resolve(["json-glib"], installed=["json-glib", "git", "newtool"])

    assert system2.calls == ["json-glib"]  # recomputed, not served stale
    assert result["json-glib"] == ["rmlint", "newtool"]


def test_uninstalling_a_package_invalidates_the_whole_cache(cache_path: Path):
    first = DependencyResolver(_FakeSystem({"json-glib": ["rmlint"]}), cache_path)
    first.resolve(["json-glib"], installed=["json-glib", "git", "rmlint"])

    system2 = _FakeSystem({})
    second = DependencyResolver(system2, cache_path)
    result = second.resolve(["json-glib"], installed=["json-glib", "git"])

    assert system2.calls == ["json-glib"]
    assert result["json-glib"] == []


def test_only_misses_are_computed_on_a_partially_warm_cache(cache_path: Path):
    installed = ["a", "b", "c"]
    DependencyResolver(_FakeSystem({}), cache_path).resolve(["a", "b"], installed=installed)

    system2 = _FakeSystem({"c": ["someone"]})
    result = DependencyResolver(system2, cache_path).resolve(
        ["a", "b", "c"], installed=installed
    )

    assert system2.calls == ["c"]
    assert result == {"a": [], "b": [], "c": ["someone"]}


def test_required_by_single_package_uses_the_same_cache(cache_path: Path):
    installed = ["json-glib", "git"]
    DependencyResolver(_FakeSystem({"json-glib": ["rmlint"]}), cache_path).resolve(
        ["json-glib"], installed=installed
    )

    system2 = _FakeSystem({"json-glib": ["rmlint"]})
    resolver = DependencyResolver(system2, cache_path)

    assert resolver.required_by("json-glib", installed=installed) == ["rmlint"]
    assert system2.calls == []


def test_required_by_computes_and_caches_a_miss(cache_path: Path):
    system = _FakeSystem({"json-glib": ["rmlint"]})
    resolver = DependencyResolver(system, cache_path)
    installed = ["json-glib"]

    assert resolver.required_by("json-glib", installed=installed) == ["rmlint"]
    assert resolver.required_by("json-glib", installed=installed) == ["rmlint"]
    assert system.calls == ["json-glib"]  # second call served from cache


def test_invalidate_forces_a_recompute(cache_path: Path):
    installed = ["json-glib"]
    system = _FakeSystem({"json-glib": ["rmlint"]})
    resolver = DependencyResolver(system, cache_path)
    resolver.resolve(["json-glib"], installed=installed)
    assert system.calls == ["json-glib"]

    resolver.invalidate()
    resolver.resolve(["json-glib"], installed=installed)

    assert system.calls == ["json-glib", "json-glib"]


def test_invalidate_also_clears_the_file(cache_path: Path):
    installed = ["json-glib"]
    resolver = DependencyResolver(_FakeSystem({}), cache_path)
    resolver.resolve(["json-glib"], installed=installed)
    assert cache_path.exists()

    resolver.invalidate()

    system2 = _FakeSystem({"json-glib": ["rmlint"]})
    assert DependencyResolver(system2, cache_path).resolve(
        ["json-glib"], installed=installed
    ) == {"json-glib": ["rmlint"]}
    assert system2.calls == ["json-glib"]  # nothing left on disk to serve it


def test_a_failing_lookup_is_not_cached(cache_path: Path):
    class Boom:
        def __init__(self):
            self.calls = []

        def get_required_by(self, package):
            self.calls.append(package)
            raise RuntimeError("subprocess blew up")

    system = Boom()
    resolver = DependencyResolver(system, cache_path)
    installed = ["json-glib"]

    assert resolver.resolve(["json-glib"], installed=installed) == {"json-glib": []}
    resolver.resolve(["json-glib"], installed=installed)

    assert system.calls == ["json-glib", "json-glib"]  # retried, not remembered


def test_resolve_forwards_progress_and_stop(cache_path: Path):
    system = _FakeSystem({})
    resolver = DependencyResolver(system, cache_path)
    seen = []

    resolver.resolve(
        ["a", "b"],
        installed=["a", "b"],
        progress=lambda done, total: seen.append((done, total)),
    )

    assert seen[-1] == (2, 2)


def test_unreadable_cache_dir_degrades_to_no_cache(tmp_path: Path, monkeypatch):
    """A cache that can't be written must still return correct results —
    just without the speedup."""
    system = _FakeSystem({"json-glib": ["rmlint"]})
    resolver = DependencyResolver(system, tmp_path / "c" / "deps.tsv")

    def boom(*args, **kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(Path, "mkdir", boom)

    assert resolver.resolve(["json-glib"], installed=["json-glib"]) == {
        "json-glib": ["rmlint"]
    }


def test_default_cache_path_lives_under_the_config_base(tmp_path: Path):
    from tui.core.dep_cache import default_cache_path

    path = default_cache_path(tmp_path)

    assert path.parent.parent == tmp_path  # <base>/cache/<file>
    assert path.suffix == ".tsv"
