"""Tests for AddPackageScreen — specifically that a package from a
third-party tap gets stored fully qualified.

Storing `clawtunes` instead of `forketyfork/tap/clawtunes` is what made
that package uninstallable on a second machine: the short name only
resolves where the tap is already tapped. Fixing it at the point of entry
means tt-fix-taps stays a one-off cleanup rather than something that has
to be re-run forever.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from textual.app import App
from textual.widgets import Input, OptionList

from tui.core.config import TTConfig
from tui.core.system import SystemInfo
from tui.screens._add_package import AddPackageScreen


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    base = tmp_path / "toolTamer"
    configs = base / "configs"
    common = configs / "common"
    common.mkdir(parents=True)
    (common / "files").mkdir()
    (common / "to_install.brew").write_text("git\n")
    (common / "files.conf").write_text("")
    host = configs / "testhost"
    host.mkdir(parents=True)
    (host / "files").mkdir()
    (host / "files.conf").write_text("")
    (host / "includes.conf").write_text("")
    (base / "tt.conf").write_text("")
    return base


class _DialogApp(App):
    def __init__(self, screen):
        super().__init__()
        self._screen_under_test = screen

    def on_mount(self) -> None:
        self.push_screen(self._screen_under_test)


async def _add(tmp_config: Path, monkeypatch, typed: str, tap: str | None) -> list[str]:
    """Drive the dialog: type `typed`, pick the "common" config, return
    what ended up in common/to_install.brew."""
    with patch("socket.gethostname", return_value="testhost"):
        system = SystemInfo()
    monkeypatch.setattr(system, "installer", "brew", raising=False)
    monkeypatch.setattr(system, "get_package_tap", lambda pkg: tap)

    screen = AddPackageScreen(TTConfig(tmp_config), system)
    app = _DialogApp(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen.query_one("#pkg-name-input", Input).value = typed
        options = screen.query_one("#config-list", OptionList)
        idx = next(
            i for i in range(options.option_count)
            if str(options.get_option_at_index(i).id) == "common"
        )
        options.highlighted = idx
        options.action_select()
        await pilot.pause()

    return (tmp_config / "configs" / "common" / "to_install.brew").read_text().split()


@pytest.mark.asyncio
async def test_tap_package_is_stored_fully_qualified(tmp_config: Path, monkeypatch):
    packages = await _add(
        tmp_config, monkeypatch, typed="clawtunes", tap="forketyfork/tap"
    )

    assert "forketyfork/tap/clawtunes" in packages
    assert "clawtunes" not in packages


@pytest.mark.asyncio
async def test_core_package_is_stored_unchanged(tmp_config: Path, monkeypatch):
    packages = await _add(tmp_config, monkeypatch, typed="ripgrep", tap=None)

    assert "ripgrep" in packages
    assert not any("/" in p for p in packages)


@pytest.mark.asyncio
async def test_an_already_qualified_name_is_not_double_qualified(
    tmp_config: Path, monkeypatch
):
    packages = await _add(
        tmp_config,
        monkeypatch,
        typed="forketyfork/tap/clawtunes",
        tap="forketyfork/tap",
    )

    assert packages.count("forketyfork/tap/clawtunes") == 1
    assert "forketyfork/tap/forketyfork/tap/clawtunes" not in packages


@pytest.mark.asyncio
async def test_tap_lookup_failure_falls_back_to_the_typed_name(
    tmp_config: Path, monkeypatch
):
    """The tap lookup is a subprocess call — if it fails, still add the
    package rather than losing the user's input."""
    with patch("socket.gethostname", return_value="testhost"):
        system = SystemInfo()
    monkeypatch.setattr(system, "installer", "brew", raising=False)

    def boom(pkg):
        raise RuntimeError("brew exploded")

    monkeypatch.setattr(system, "get_package_tap", boom)

    screen = AddPackageScreen(TTConfig(tmp_config), system)
    app = _DialogApp(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen.query_one("#pkg-name-input", Input).value = "sometool"
        options = screen.query_one("#config-list", OptionList)
        idx = next(
            i for i in range(options.option_count)
            if str(options.get_option_at_index(i).id) == "common"
        )
        options.highlighted = idx
        options.action_select()
        await pilot.pause()

    packages = (tmp_config / "configs" / "common" / "to_install.brew").read_text().split()
    assert "sometool" in packages
