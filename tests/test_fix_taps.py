"""Tests for tap-qualified package names (tt-fix-taps).

A package from a third-party tap only installs on a fresh machine if
brew can resolve its name. `brew install clawtunes` fails there — the tap
isn't tapped yet, so the short name means nothing. `brew install
forketyfork/tap/clawtunes` works, because brew taps automatically when
given a fully qualified name.

So packages from third-party taps belong in to_install.brew fully
qualified. This finds the ones that aren't and rewrites them.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from tui.core.config import TTConfig
from tui.core.system import SystemInfo
from tui.fix_taps import find_short_tap_names, main


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """common: git (core), clawtunes (tap, SHORT name — needs fixing).
    host: forketyfork/tap/other (tap, already fully qualified — fine)."""
    base = tmp_path / "toolTamer"
    configs = base / "configs"
    common = configs / "common"
    common.mkdir(parents=True)
    (common / "files").mkdir()
    (common / "to_install.brew").write_text("git\nclawtunes\nnot-installed\n")
    (common / "files.conf").write_text("")
    host = configs / "testhost"
    host.mkdir(parents=True)
    (host / "files").mkdir()
    (host / "to_install.brew").write_text("forketyfork/tap/other\n")
    (host / "files.conf").write_text("")
    (host / "includes.conf").write_text("")
    (base / "tt.conf").write_text("")
    return base


def _system(monkeypatch, full_names: dict[str, str]) -> SystemInfo:
    with patch("socket.gethostname", return_value="testhost"):
        system = SystemInfo()
    monkeypatch.setattr(
        system, "list_installed_packages",
        lambda: ["git", "clawtunes", "other"],
    )
    monkeypatch.setattr(system, "list_package_full_names", lambda: full_names)
    return system


def test_finds_a_short_tap_name(tmp_config: Path, monkeypatch):
    system = _system(monkeypatch, {"clawtunes": "forketyfork/tap/clawtunes"})

    found = find_short_tap_names(TTConfig(tmp_config), system)

    assert found == [("common", "clawtunes", "forketyfork/tap/clawtunes")]


def test_ignores_core_packages(tmp_config: Path, monkeypatch):
    """git has no third-party tap, so it never appears in the full-name
    map and must not be touched."""
    system = _system(monkeypatch, {"clawtunes": "forketyfork/tap/clawtunes"})

    found = find_short_tap_names(TTConfig(tmp_config), system)

    assert all(pkg != "git" for _, pkg, _ in found)


def test_ignores_already_qualified_entries(tmp_config: Path, monkeypatch):
    system = _system(
        monkeypatch,
        {"clawtunes": "forketyfork/tap/clawtunes", "other": "forketyfork/tap/other"},
    )

    found = find_short_tap_names(TTConfig(tmp_config), system)

    assert all("/" not in pkg for _, pkg, _ in found)
    assert ("testhost", "other", "forketyfork/tap/other") not in found


def test_ignores_packages_that_are_not_installed(tmp_config: Path, monkeypatch):
    """Tap membership can only be read off an installed package, so an
    uninstalled config entry is left alone rather than guessed at."""
    system = _system(
        monkeypatch, {"not-installed": "some/tap/not-installed"}
    )

    found = find_short_tap_names(TTConfig(tmp_config), system)

    assert all(pkg != "not-installed" for _, pkg, _ in found)


def test_returns_empty_when_nothing_to_fix(tmp_config: Path, monkeypatch):
    assert find_short_tap_names(TTConfig(tmp_config), _system(monkeypatch, {})) == []


def _run_main(monkeypatch, tmp_config, full_names, argv, input_answer=None):
    system = _system(monkeypatch, full_names)
    monkeypatch.setattr("tui.fix_taps.SystemInfo", lambda base=None: system)
    monkeypatch.setattr("tui.fix_taps.TTConfig", lambda base: TTConfig(tmp_config))
    monkeypatch.setenv("TT_BASE", str(tmp_config))
    if input_answer is not None:
        monkeypatch.setattr("builtins.input", lambda prompt="": input_answer)
    return main(argv)


def test_main_dry_run_changes_nothing(tmp_config: Path, monkeypatch, capsys):
    code = _run_main(
        monkeypatch, tmp_config, {"clawtunes": "forketyfork/tap/clawtunes"}, []
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "clawtunes" in out and "Dry run" in out
    assert "clawtunes\n" in (
        tmp_config / "configs" / "common" / "to_install.brew"
    ).read_text()


def test_main_apply_rewrites_the_entry_in_place(tmp_config: Path, monkeypatch):
    code = _run_main(
        monkeypatch,
        tmp_config,
        {"clawtunes": "forketyfork/tap/clawtunes"},
        ["--apply", "--yes"],
    )

    assert code == 0
    content = (tmp_config / "configs" / "common" / "to_install.brew").read_text()
    lines = content.split()
    assert "forketyfork/tap/clawtunes" in lines
    assert "clawtunes" not in lines  # replaced, not duplicated
    assert "git" in lines  # untouched
    assert "not-installed" in lines


def test_main_apply_aborts_on_no(tmp_config: Path, monkeypatch):
    code = _run_main(
        monkeypatch,
        tmp_config,
        {"clawtunes": "forketyfork/tap/clawtunes"},
        ["--apply"],
        input_answer="n",
    )

    assert code == 1
    assert "clawtunes\n" in (
        tmp_config / "configs" / "common" / "to_install.brew"
    ).read_text()


def test_main_reports_when_nothing_to_fix(tmp_config: Path, monkeypatch, capsys):
    code = _run_main(monkeypatch, tmp_config, {}, [])

    assert code == 0
    assert "All tap packages" in capsys.readouterr().out


# --- SystemInfo.list_package_full_names ------------------------------


def test_list_package_full_names_maps_short_to_qualified(monkeypatch):
    import json
    import subprocess

    system = SystemInfo()
    system.installer = "brew"
    payload = {
        "formulae": [
            {"name": "git", "tap": "homebrew/core", "full_name": "git"},
            {
                "name": "clawtunes",
                "tap": "forketyfork/tap",
                "full_name": "forketyfork/tap/clawtunes",
            },
        ],
        "casks": [],
    }

    def fake_run(cmd, **kwargs):
        assert cmd == ["brew", "info", "--json=v2", "--installed"]
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = system.list_package_full_names()

    assert result == {"clawtunes": "forketyfork/tap/clawtunes"}  # core excluded


def test_list_package_full_names_includes_casks(monkeypatch):
    import json
    import subprocess

    system = SystemInfo()
    system.installer = "brew"
    payload = {
        "formulae": [],
        "casks": [
            {"token": "sometool", "tap": "homebrew/cask", "full_token": "sometool"},
            {
                "token": "othertool",
                "tap": "someone/tap",
                "full_token": "someone/tap/othertool",
            },
        ],
    }
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr=""),
    )

    assert system.list_package_full_names() == {"othertool": "someone/tap/othertool"}


def test_list_package_full_names_empty_for_non_brew(monkeypatch):
    import subprocess

    system = SystemInfo()
    system.installer = "apt"

    def fail(*a, **kw):
        raise AssertionError("must not shell out for a non-brew installer")

    monkeypatch.setattr(subprocess, "run", fail)

    assert system.list_package_full_names() == {}


def test_list_package_full_names_survives_bad_json(monkeypatch):
    import subprocess

    system = SystemInfo()
    system.installer = "brew"
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="not json", stderr=""),
    )

    assert system.list_package_full_names() == {}
