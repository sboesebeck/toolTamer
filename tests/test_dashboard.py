import os
from pathlib import Path
from unittest.mock import patch

import pytest
from textual.widgets import Header, Footer, Input, ListView

from tui.core.system import SystemInfo
from tui.screens._machine_id import MachineIdScreen
from tui.widgets.config_tree import ConfigHierarchy

from tui.app import ToolTamerApp


@pytest.fixture
def app(tmp_config: Path, monkeypatch) -> ToolTamerApp:
    # StatusBar._scan_status runs on every dashboard mount with a real,
    # unmocked SystemInfo here (list_installed_packages/
    # list_dependency_packages stay real — this fixture predates that
    # being an issue). Since the refinement pass added there now does one
    # get_required_by() subprocess call per "excess" package, that could
    # be a lot of real, slow calls on a dev machine with many installed-
    # but-untracked packages (this test's own tmp_config chain only has a
    # handful of packages, so almost everything actually installed counts
    # as excess). Mock just that one call to keep this bounded and fast
    # regardless of what's really installed here.
    monkeypatch.setattr(SystemInfo, "get_required_by", lambda self, pkg: [])
    with patch.dict(os.environ, {"TT_BASE": str(tmp_config)}):
        with patch("socket.gethostname", return_value="testhost"):
            return ToolTamerApp()


@pytest.mark.asyncio
async def test_dashboard_has_header_and_footer(app: ToolTamerApp):
    async with app.run_test() as pilot:
        assert app.query_one(Header)
        assert app.query_one(Footer)


@pytest.mark.asyncio
async def test_dashboard_shows_hostname(app: ToolTamerApp):
    async with app.run_test() as pilot:
        label = app.query_one("#host-value")
        assert "testhost" in str(label.render())


@pytest.mark.asyncio
async def test_dashboard_has_menu(app: ToolTamerApp):
    async with app.run_test() as pilot:
        menu = app.query_one(ListView)
        assert menu is not None


@pytest.mark.asyncio
async def test_dashboard_has_config_hierarchy(app: ToolTamerApp):
    async with app.run_test() as pilot:
        hierarchy = app.query_one(ConfigHierarchy)
        assert hierarchy is not None


@pytest.mark.asyncio
async def test_dashboard_host_shows_real_hostname_when_pinned(tmp_config: Path, monkeypatch):
    # machine-id pins the config name; the status bar must still reveal
    # what the network currently calls the machine, otherwise a stale
    # machine-id is invisible.
    monkeypatch.setattr(SystemInfo, "get_required_by", lambda self, pkg: [])
    (tmp_config / "machine-id").write_text("testhost\n")
    with patch.dict(os.environ, {"TT_BASE": str(tmp_config)}):
        with patch("socket.gethostname", return_value="testhost.vpn.example"):
            app = ToolTamerApp()
    async with app.run_test():
        label = app.query_one("#host-value")
        assert "testhost (testhost.vpn.example)" in str(label.render())


@pytest.mark.asyncio
async def test_dashboard_host_has_no_suffix_when_names_agree(app: ToolTamerApp):
    async with app.run_test():
        text = str(app.query_one("#host-value").render())
        assert "testhost" in text
        assert "testhost (" not in text


# --- Machine ID menu entry -------------------------------------------------


def _app_in_repo(tmp_config: Path, monkeypatch) -> ToolTamerApp:
    monkeypatch.setattr(SystemInfo, "get_required_by", lambda self, pkg: [])
    (tmp_config / ".git").mkdir()
    (tmp_config / ".gitignore").write_text("cache/\n")
    with patch.dict(os.environ, {"TT_BASE": str(tmp_config)}):
        with patch("socket.gethostname", return_value="testhost"):
            return ToolTamerApp()


@pytest.mark.asyncio
async def test_machine_id_dialog_opens_prefilled(tmp_config: Path, monkeypatch):
    app = _app_in_repo(tmp_config, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.press("m")
        await pilot.pause()
        assert isinstance(app.screen, MachineIdScreen)
        assert app.screen.query_one("#machine-id-input", Input).value == "testhost"


@pytest.mark.asyncio
async def test_new_machine_id_renames_config_and_redraws(tmp_config: Path, monkeypatch):
    app = _app_in_repo(tmp_config, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.press("m")
        await pilot.pause()
        app.screen.query_one("#machine-id-input", Input).value = "gandalf"
        await pilot.press("enter")
        await pilot.pause()

        assert (tmp_config / "machine-id").read_text() == "gandalf\n"
        assert "machine-id" in (tmp_config / ".gitignore").read_text().splitlines()
        # the host config moved with the id
        assert (tmp_config / "configs" / "gandalf" / "to_install.brew").exists()
        assert not (tmp_config / "configs" / "testhost").exists()
        # and the dashboard now shows the new name next to the live hostname
        assert not isinstance(app.screen, MachineIdScreen)
        assert "gandalf (testhost)" in str(app.screen.query_one("#host-value").render())


@pytest.mark.asyncio
async def test_switching_to_existing_config_does_not_move_anything(tmp_config: Path, monkeypatch):
    app = _app_in_repo(tmp_config, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.press("m")
        await pilot.pause()
        app.screen.query_one("#machine-id-input", Input).value = "macosx"
        await pilot.press("enter")
        await pilot.pause()

        assert (tmp_config / "machine-id").read_text() == "macosx\n"
        assert (tmp_config / "configs" / "testhost").is_dir()
        assert (tmp_config / "configs" / "macosx").is_dir()
        assert "macosx (testhost)" in str(app.screen.query_one("#host-value").render())


@pytest.mark.asyncio
async def test_escape_or_unchanged_id_changes_nothing(tmp_config: Path, monkeypatch):
    app = _app_in_repo(tmp_config, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.press("m")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not (tmp_config / "machine-id").exists()

        await pilot.press("m")
        await pilot.pause()
        await pilot.press("enter")  # value still "testhost"
        await pilot.pause()
        assert not (tmp_config / "machine-id").exists()
        assert not isinstance(app.screen, MachineIdScreen)


@pytest.mark.asyncio
async def test_machine_id_must_be_a_plain_directory_name(tmp_config: Path, monkeypatch):
    app = _app_in_repo(tmp_config, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.press("m")
        await pilot.pause()
        app.screen.query_one("#machine-id-input", Input).value = "foo/bar"
        await pilot.press("enter")
        await pilot.pause()
        # rejected: dialog stays open, nothing written
        assert isinstance(app.screen, MachineIdScreen)
        assert not (tmp_config / "machine-id").exists()


# --- dangling includes ------------------------------------------------------


@pytest.mark.asyncio
async def test_status_bar_flags_missing_include_in_chain(tmp_config: Path, monkeypatch):
    (tmp_config / "configs" / "testhost" / "includes.conf").write_text("macosx\ngone\n")
    app = _app_in_repo(tmp_config, monkeypatch)
    async with app.run_test():
        text = str(app.screen.query_one("#configs-value").render())
        assert "gone (missing)" in text
        assert "macosx" in text


@pytest.mark.asyncio
async def test_status_bar_chain_is_plain_when_complete(app: ToolTamerApp):
    async with app.run_test():
        assert "missing" not in str(app.screen.query_one("#configs-value").render())


@pytest.mark.asyncio
async def test_machine_id_hint_names_configs_whose_includes_move(tmp_config: Path, monkeypatch):
    other = tmp_config / "configs" / "otherhost"
    other.mkdir()
    (other / "includes.conf").write_text("testhost\n")
    app = _app_in_repo(tmp_config, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.press("m")
        await pilot.pause()
        app.screen.query_one("#machine-id-input", Input).value = "gandalf"
        await pilot.pause()
        hint = str(app.screen.query_one("#machine-id-hint").render())
        assert "otherhost" in hint
        await pilot.press("enter")
        await pilot.pause()
        assert (other / "includes.conf").read_text() == "gandalf\n"


# -- Layout on short terminals ---------------------------------------------
#
# The dashboard used to need ~43 rows before the last menu entry was on
# screen; the Container clipped the rest silently and the ListView (height:
# auto) could never scroll. These pin the compact layout and the scroll
# fallback. 24 rows (the classic minimum terminal) now fits everything
# even with missing/extra detail lines; the 30-row check stays robust to
# however many packages the dev machine really has installed, and 20 rows
# forces the scroll path.


@pytest.mark.asyncio
async def test_dashboard_status_and_hierarchy_side_by_side(app: ToolTamerApp):
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        status = app.screen.query_one("#status-panel")
        hierarchy = app.screen.query_one("#hierarchy-panel")
        assert status.region.y == hierarchy.region.y
        assert status.region.x < hierarchy.region.x


@pytest.mark.asyncio
async def test_dashboard_menu_fits_on_30_rows(app: ToolTamerApp):
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        menu = app.screen.query_one(ListView)
        items = list(menu.query("ListItem"))
        assert menu.max_scroll_y == 0
        assert items[-1].region.bottom <= 30 - 1  # above the docked Footer


@pytest.mark.asyncio
async def test_dashboard_menu_scrolls_on_20_rows(app: ToolTamerApp):
    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.pause()
        menu = app.screen.query_one(ListView)
        # The list itself must stay on screen (not be clipped by its panel)...
        assert menu.region.bottom <= 20 - 1
        # ...and take over via scrolling instead of hiding the tail.
        assert menu.max_scroll_y > 0
        menu.index = len(list(menu.query("ListItem"))) - 1
        await pilot.pause()
        assert menu.scroll_y > 0
