"""Tests for the reverse-dependency cache warm-up (tui/warm_deps.py).

The sync in bin/tt asks depCount() about every installed package the
config doesn't list — on a real machine that is hundreds of packages,
while the TUI only ever populates the cache for the much smaller set it
displays. This tool fills exactly the sync's set, in parallel, so the
serial bash-side lookups become cache hits.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from tui.core.config import TTConfig
from tui.core.dep_cache import default_cache_path, fingerprint
from tui.core.system import SystemInfo
from tui.warm_deps import candidates_from_config, main


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """common tracks git and fzf, the host tracks a tap-qualified
    package whose installed name is short (clawtunes)."""
    base = tmp_path / "toolTamer"
    configs = base / "configs"
    common = configs / "common"
    common.mkdir(parents=True)
    (common / "files").mkdir()
    (common / "to_install.brew").write_text("git\nfzf\n")
    (common / "files.conf").write_text("")
    host = configs / "testhost"
    host.mkdir(parents=True)
    (host / "files").mkdir()
    (host / "to_install.brew").write_text("forketyfork/tap/clawtunes\n")
    (host / "files.conf").write_text("")
    (host / "includes.conf").write_text("")
    (base / "tt.conf").write_text("")
    return base


def _system(monkeypatch, required_by_map: dict, installed: list[str]):
    """SystemInfo with both package-manager calls stubbed; returns the
    system plus the list of packages get_required_by was actually asked
    about, so tests can assert cache hits skipped the expensive call."""
    with patch("socket.gethostname", return_value="testhost"):
        system = SystemInfo()
    monkeypatch.setattr(system, "list_installed_packages", lambda: list(installed))
    calls: list[str] = []

    def get_required_by(pkg):
        calls.append(pkg)
        result = required_by_map.get(pkg, [])
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(system, "get_required_by", get_required_by)
    return system, calls


class TestCandidatesFromConfig:
    def test_returns_installed_packages_no_config_lists(self, tmp_config, monkeypatch):
        installed = ["git", "fzf", "clawtunes", "json-glib", "icu4c@77"]
        system, _ = _system(monkeypatch, {}, installed)
        cands = candidates_from_config(TTConfig(tmp_config), system, installed)
        assert cands == ["icu4c@77", "json-glib"]

    def test_tap_qualified_config_entry_matches_short_installed_name(
        self, tmp_config, monkeypatch
    ):
        """clawtunes is tracked as forketyfork/tap/clawtunes but installed
        as clawtunes — comparing the raw strings would make it a candidate
        and waste a lookup on a package the sync never asks about."""
        installed = ["clawtunes"]
        system, _ = _system(monkeypatch, {}, installed)
        assert candidates_from_config(TTConfig(tmp_config), system, installed) == []

    def test_no_candidates_when_everything_is_tracked(self, tmp_config, monkeypatch):
        installed = ["git", "fzf"]
        system, _ = _system(monkeypatch, {}, installed)
        assert candidates_from_config(TTConfig(tmp_config), system, installed) == []


class TestWarmUp:
    def test_writes_cache_for_the_given_candidates(self, tmp_config, monkeypatch):
        installed = ["git", "fzf", "json-glib", "rmlint"]
        system, calls = _system(
            monkeypatch, {"json-glib": ["rmlint"], "rmlint": []}, installed
        )
        cand_file = tmp_config / "cands"
        cand_file.write_text("json-glib\nrmlint\n")

        rc = main(
            ["--candidates", str(cand_file)],
            tt_config=TTConfig(tmp_config),
            system=system,
        )

        assert rc == 0
        assert sorted(calls) == ["json-glib", "rmlint"]
        cache = default_cache_path(tmp_config).read_text()
        assert f"# fingerprint {fingerprint(installed)}" in cache
        assert "json-glib\trmlint" in cache
        # No dependents is a real cached answer, written as an empty field.
        assert "rmlint\t" in cache

    def test_already_cached_packages_are_not_looked_up_again(
        self, tmp_config, monkeypatch
    ):
        installed = ["git", "json-glib", "rmlint"]
        cache_path = default_cache_path(tmp_config)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            "# tooltamer reverse-dependency cache v1\n"
            f"# fingerprint {fingerprint(installed)}\n"
            "json-glib\trmlint\n"
        )
        system, calls = _system(monkeypatch, {"rmlint": []}, installed)
        cand_file = tmp_config / "cands"
        cand_file.write_text("json-glib\nrmlint\n")

        main(["--candidates", str(cand_file)], tt_config=TTConfig(tmp_config), system=system)

        assert calls == ["rmlint"]
        assert "json-glib\trmlint" in cache_path.read_text()

    def test_candidate_file_ignores_blanks_and_comments(self, tmp_config, monkeypatch):
        installed = ["git", "json-glib"]
        system, calls = _system(monkeypatch, {"json-glib": []}, installed)
        cand_file = tmp_config / "cands"
        cand_file.write_text("\n# a comment\njson-glib\n\n")

        main(["--candidates", str(cand_file)], tt_config=TTConfig(tmp_config), system=system)

        assert calls == ["json-glib"]

    def test_installed_file_defines_the_fingerprint(self, tmp_config, monkeypatch):
        """bin/tt already has the installed list in $TMP/local_installed and
        checks the cache against it. Re-deriving it here could disagree, and
        a fingerprint the bash side doesn't recognize invalidates the whole
        warm-up."""
        installed = ["git", "json-glib"]
        system, _ = _system(monkeypatch, {"json-glib": []}, ["git", "json-glib", "drifted"])
        inst_file = tmp_config / "installed"
        inst_file.write_text("git\njson-glib\n")
        cand_file = tmp_config / "cands"
        cand_file.write_text("json-glib\n")

        main(
            ["--candidates", str(cand_file), "--installed", str(inst_file)],
            tt_config=TTConfig(tmp_config),
            system=system,
        )

        cache = default_cache_path(tmp_config).read_text()
        assert f"# fingerprint {fingerprint(installed)}" in cache

    def test_installed_list_keeps_names_the_candidate_filter_would_drop(
        self, tmp_config, monkeypatch
    ):
        """The installed list feeds the fingerprint, which bin/tt computes
        with `sed '/^$/d' | sort -u` — blank lines only. Applying the
        candidate filter (which also drops '#' and '=') to it would
        produce a hash the bash side rejects, throwing the warm-up away."""
        installed = ["git", "weird=name", "odd#name"]
        system, _ = _system(monkeypatch, {"git": []}, installed)
        inst_file = tmp_config / "installed"
        inst_file.write_text("git\nweird=name\n\nodd#name\n")
        cand_file = tmp_config / "cands"
        cand_file.write_text("git\n")

        main(
            ["--candidates", str(cand_file), "--installed", str(inst_file)],
            tt_config=TTConfig(tmp_config),
            system=system,
        )

        cache = default_cache_path(tmp_config).read_text()
        assert f"# fingerprint {fingerprint(installed)}" in cache

    def test_without_candidate_file_it_derives_them_from_the_config(
        self, tmp_config, monkeypatch
    ):
        installed = ["git", "fzf", "json-glib"]
        system, calls = _system(monkeypatch, {"json-glib": []}, installed)

        rc = main([], tt_config=TTConfig(tmp_config), system=system)

        assert rc == 0
        assert calls == ["json-glib"]

    def test_failed_lookup_is_not_cached_as_no_dependents(self, tmp_config, monkeypatch):
        """A lookup that blew up must not be remembered as a confirmed
        "nothing needs this" — that is the direction that makes the sync
        uninstall something still in use."""
        installed = ["git", "json-glib"]
        system, _ = _system(monkeypatch, {"json-glib": RuntimeError("boom")}, installed)
        cand_file = tmp_config / "cands"
        cand_file.write_text("json-glib\n")

        rc = main(["--candidates", str(cand_file)], tt_config=TTConfig(tmp_config), system=system)

        assert rc == 0
        cache = default_cache_path(tmp_config)
        if cache.exists():
            assert "json-glib\t" not in cache.read_text()

    def test_missing_candidate_file_is_reported_not_crashed(self, tmp_config, monkeypatch):
        system, calls = _system(monkeypatch, {}, ["git"])

        rc = main(
            ["--candidates", str(tmp_config / "nope")],
            tt_config=TTConfig(tmp_config),
            system=system,
        )

        assert rc == 1
        assert calls == []

    def test_nothing_to_do_is_success(self, tmp_config, monkeypatch):
        system, calls = _system(monkeypatch, {}, ["git", "fzf"])
        cand_file = tmp_config / "cands"
        cand_file.write_text("")

        assert main(["--candidates", str(cand_file)], tt_config=TTConfig(tmp_config), system=system) == 0
        assert calls == []
