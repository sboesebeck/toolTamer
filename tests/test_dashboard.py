import os
from pathlib import Path
from unittest.mock import patch

import pytest
from textual.widgets import Header, Footer, ListView

from tui.core.system import SystemInfo
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
