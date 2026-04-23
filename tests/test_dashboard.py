import os
from pathlib import Path
from unittest.mock import patch

import pytest
from textual.widgets import Header, Footer, ListView, Tree

from tui.app import ToolTamerApp


@pytest.fixture
def app(tmp_config: Path) -> ToolTamerApp:
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
async def test_dashboard_has_config_tree(app: ToolTamerApp):
    async with app.run_test() as pilot:
        tree = app.query_one(Tree)
        assert tree is not None
