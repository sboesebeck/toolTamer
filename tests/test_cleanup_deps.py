"""Tests for the one-off dependency-cleanup script (tui/cleanup_deps.py).

Removes packages from to_install.* files that are only tracked there
because the old syncInstall() bug (fixed in bin/tt) used to persist
detected dependencies into the config. Scoped to the current host's
resolved chain only — get_required_by() needs real installed-package
data, which is only trustworthy for packages actually installed on the
machine running this script.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from tui.cleanup_deps import find_candidates, main
from tui.core.config import TTConfig
from tui.core.system import SystemInfo


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """common: git, fzf, json-glib (json-glib is a dependency that
    shouldn't be here). host: vim (genuinely wanted, also happens to be
    depended on by something else — must NOT be treated as a removal
    candidate just because it's required_by-positive: it's also a
    tracked package in its own right). wget: in common but not
    installed — must be skipped, its dependency status can't be
    verified."""
    base = tmp_path / "toolTamer"
    configs = base / "configs"
    common = configs / "common"
    common.mkdir(parents=True)
    (common / "files").mkdir()
    (common / "to_install.brew").write_text("git\nfzf\njson-glib\nwget\n")
    (common / "files.conf").write_text("")
    host = configs / "testhost"
    host.mkdir(parents=True)
    (host / "files").mkdir()
    (host / "to_install.brew").write_text("vim\n")
    (host / "files.conf").write_text("")
    (host / "includes.conf").write_text("")
    (base / "tt.conf").write_text("")
    return base


def _system(
    monkeypatch, required_by_map: dict, dep_only: set[str] = frozenset()
) -> SystemInfo:
    with patch("socket.gethostname", return_value="testhost"):
        system = SystemInfo()
    monkeypatch.setattr(
        system, "list_installed_packages",
        lambda: ["git", "fzf", "json-glib", "vim"],  # wget NOT installed
    )
    monkeypatch.setattr(system, "list_dependency_packages", lambda: set(dep_only))
    calls: list[str] = []

    def get_required_by(pkg):
        calls.append(pkg)
        return required_by_map.get(pkg, [])

    monkeypatch.setattr(system, "get_required_by", get_required_by)
    system._test_calls = calls  # type: ignore[attr-defined]
    return system


def test_find_candidates_flags_installed_packages_required_by_something(
    tmp_config: Path, monkeypatch
):
    system = _system(
        monkeypatch,
        {"json-glib": ["gnome-control-center"], "vim": ["some-plugin-host"]},
    )
    tt_config = TTConfig(tmp_config)

    candidates = find_candidates(tt_config, system)

    names = {(cfg, pkg) for cfg, pkg, _ in candidates}
    assert ("common", "json-glib") in names
    assert ("testhost", "vim") in names
    assert ("common", "git") not in names  # not required by anything
    assert ("common", "wget") not in names  # not installed — can't verify


def test_find_candidates_returns_the_required_by_reason(tmp_config: Path, monkeypatch):
    system = _system(monkeypatch, {"json-glib": ["gnome-control-center", "other-pkg"]})
    tt_config = TTConfig(tmp_config)

    candidates = find_candidates(tt_config, system)

    match = next(c for c in candidates if c[1] == "json-glib")
    assert match[2] == ["gnome-control-center", "other-pkg"]


def test_find_candidates_empty_when_nothing_required(tmp_config: Path, monkeypatch):
    system = _system(monkeypatch, {})
    tt_config = TTConfig(tmp_config)

    assert find_candidates(tt_config, system) == []


def test_find_candidates_uses_the_cheap_signal_first(tmp_config: Path, monkeypatch):
    """list_dependency_packages() (one call for the whole set, install
    *reason*) is checked before get_required_by() (one call per package,
    structural) — a package it already flags doesn't need the expensive
    per-package check too."""
    system = _system(monkeypatch, {}, dep_only={"json-glib"})
    tt_config = TTConfig(tmp_config)

    candidates = find_candidates(tt_config, system)

    names = {(cfg, pkg) for cfg, pkg, _ in candidates}
    assert ("common", "json-glib") in names
    assert "json-glib" not in system._test_calls  # cheap signal was enough


def test_find_candidates_fast_mode_skips_the_expensive_check(
    tmp_config: Path, monkeypatch
):
    """--fast: only the cheap list_dependency_packages() signal — no
    get_required_by() calls at all, however many packages are in the
    chain. Trades catching cases like json-glib (which the cheap signal
    alone misses) for a near-instant result on a config with hundreds of
    packages."""
    system = _system(
        monkeypatch,
        {"json-glib": ["gnome-control-center"]},  # would be found if checked
    )
    tt_config = TTConfig(tmp_config)

    candidates = find_candidates(tt_config, system, fast=True)

    assert candidates == []
    assert system._test_calls == []  # get_required_by never called


def test_find_candidates_reports_progress_for_the_expensive_check(
    tmp_config: Path, monkeypatch
):
    system = _system(monkeypatch, {"json-glib": ["gnome-control-center"]})
    tt_config = TTConfig(tmp_config)
    progress_calls = []

    find_candidates(tt_config, system, progress=lambda done, total: progress_calls.append((done, total)))

    assert progress_calls  # at least one update
    assert progress_calls[-1][0] == progress_calls[-1][1]  # ends at done == total


def _run_main(
    monkeypatch, tmp_config, required_by_map, argv, input_answer=None, dep_only=frozenset()
):
    system = _system(monkeypatch, required_by_map, dep_only=dep_only)
    monkeypatch.setattr("tui.cleanup_deps.SystemInfo", lambda base=None: system)
    monkeypatch.setattr("tui.cleanup_deps.TTConfig", lambda base: TTConfig(tmp_config))
    # TT_BASE must point at the temp config too, not just TTConfig: main()
    # also derives the dependency cache path from it. Without this the
    # tests read and write the *real* ~/.config/toolTamer cache — which
    # both leaks fake test data into the user's cache and lets results
    # bleed between tests (caught exactly that way).
    monkeypatch.setenv("TT_BASE", str(tmp_config))
    if input_answer is not None:
        monkeypatch.setattr("builtins.input", lambda prompt="": input_answer)
    return main(argv)


def test_main_dry_run_by_default_changes_nothing(tmp_config: Path, monkeypatch, capsys):
    exit_code = _run_main(
        monkeypatch, tmp_config, {"json-glib": ["gnome-control-center"]}, []
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "json-glib" in out
    assert "Dry run" in out
    assert (tmp_config / "configs" / "common" / "to_install.brew").read_text() == (
        "git\nfzf\njson-glib\nwget\n"
    )


def test_main_apply_without_yes_asks_and_aborts_on_no(
    tmp_config: Path, monkeypatch, capsys
):
    exit_code = _run_main(
        monkeypatch,
        tmp_config,
        {"json-glib": ["gnome-control-center"]},
        ["--apply"],
        input_answer="n",
    )

    assert exit_code == 1
    assert "json-glib" in (
        tmp_config / "configs" / "common" / "to_install.brew"
    ).read_text()


def test_main_apply_with_yes_confirmation_removes_candidates(
    tmp_config: Path, monkeypatch, capsys
):
    exit_code = _run_main(
        monkeypatch,
        tmp_config,
        {"json-glib": ["gnome-control-center"], "vim": ["some-plugin-host"]},
        ["--apply"],
        input_answer="y",
    )

    assert exit_code == 0
    common = (tmp_config / "configs" / "common" / "to_install.brew").read_text().split()
    assert "json-glib" not in common
    assert "git" in common and "fzf" in common and "wget" in common
    host = (tmp_config / "configs" / "testhost" / "to_install.brew").read_text().split()
    assert "vim" not in host


def test_main_apply_yes_flag_skips_the_prompt(tmp_config: Path, monkeypatch):
    exit_code = _run_main(
        monkeypatch,
        tmp_config,
        {"json-glib": ["gnome-control-center"]},
        ["--apply", "--yes"],
    )

    assert exit_code == 0
    common = (tmp_config / "configs" / "common" / "to_install.brew").read_text().split()
    assert "json-glib" not in common


def test_main_keep_excludes_a_package_even_if_flagged(tmp_config: Path, monkeypatch):
    exit_code = _run_main(
        monkeypatch,
        tmp_config,
        {"json-glib": ["gnome-control-center"]},
        ["--apply", "--yes", "--keep", "json-glib"],
    )

    assert exit_code == 0
    common = (tmp_config / "configs" / "common" / "to_install.brew").read_text().split()
    assert "json-glib" in common  # kept despite looking like a dependency


def test_main_reports_when_nothing_found(tmp_config: Path, monkeypatch, capsys):
    exit_code = _run_main(monkeypatch, tmp_config, {}, [])

    assert exit_code == 0
    assert "No dependency-only packages" in capsys.readouterr().out


def test_main_fast_flag_reaches_find_candidates(tmp_config: Path, monkeypatch, capsys):
    """--fast on the CLI must actually skip the expensive check, not just
    exist as an unused flag."""
    exit_code = _run_main(
        monkeypatch,
        tmp_config,
        {"json-glib": ["gnome-control-center"]},
        ["--fast"],
    )

    assert exit_code == 0
    assert "No dependency-only packages" in capsys.readouterr().out
