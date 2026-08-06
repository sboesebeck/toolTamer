"""Tests for the Dep column, caching, and hide-toggle in PackageScreen."""

from pathlib import Path
from unittest.mock import patch

import pytest
from textual.app import App
from textual.widgets import DataTable

from tui.core.config import TTConfig
from tui.core.system import SystemInfo
from tui.screens.packages import PackageScreen


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
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
    (host / "files.conf").write_text("")
    (host / "includes.conf").write_text("")
    (base / "tt.conf").write_text("")
    return base


@pytest.fixture
def tmp_config_many_packages(tmp_path: Path) -> Path:
    """Same shape as tmp_config, but with enough packages that PageDown
    visibly moves the cursor by more than one row."""
    base = tmp_path / "toolTamer"
    configs = base / "configs"
    common = configs / "common"
    common.mkdir(parents=True)
    (common / "files").mkdir()
    pkgs = "\n".join(f"pkg{i:02d}" for i in range(30))
    (common / "to_install.brew").write_text(pkgs + "\n")
    (common / "files.conf").write_text("")
    host = configs / "testhost"
    host.mkdir(parents=True)
    (host / "files").mkdir()
    (host / "files.conf").write_text("")
    (host / "includes.conf").write_text("")
    (base / "tt.conf").write_text("")
    return base


class _HarnessApp(App):
    """Minimal app whose only job is to host a PackageScreen for the test."""

    def __init__(self, tt_config: TTConfig, system: SystemInfo):
        super().__init__()
        self._tt_config = tt_config
        self._system = system

    def on_mount(self) -> None:
        self.push_screen(PackageScreen(self._tt_config, self._system))


def _visible_packages(table: DataTable) -> list[str]:
    """Read back the 'Package' column (index 1) for every currently
    visible row, in display order."""
    return [str(table.get_row(row_key)[1]) for row_key in table.rows]


def _dep_cell(table: DataTable, package: str) -> str:
    """Read back the 'Dep' column (index 2) for the row whose key ends
    with ':{package}'."""
    row_key = next(k for k in table.rows if str(k.value).endswith(f":{package}"))
    return str(table.get_row(row_key)[2])


@pytest.mark.asyncio
async def test_dep_column_marks_dependency_packages(tmp_config: Path, monkeypatch):
    monkeypatch.setattr(SystemInfo, "list_installed_packages", lambda self: ["git", "fzf"])
    monkeypatch.setattr(SystemInfo, "list_dependency_packages", lambda self: {"fzf"})

    with patch("socket.gethostname", return_value="testhost"):
        app = _HarnessApp(TTConfig(tmp_config), SystemInfo())
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, PackageScreen)
            table = screen.query_one("#pkg-table", DataTable)

            column_labels = [str(c.label) for c in table.columns.values()]
            assert column_labels == ["St", "Package", "Dep", "Config"]

            assert _dep_cell(table, "git") == ""
            assert _dep_cell(table, "fzf") == "D"


@pytest.mark.asyncio
async def test_toggle_hide_deps_removes_and_restores_rows(tmp_config: Path, monkeypatch):
    monkeypatch.setattr(SystemInfo, "list_installed_packages", lambda self: ["git", "fzf"])
    monkeypatch.setattr(SystemInfo, "list_dependency_packages", lambda self: {"fzf"})

    with patch("socket.gethostname", return_value="testhost"):
        app = _HarnessApp(TTConfig(tmp_config), SystemInfo())
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, PackageScreen)
            table = screen.query_one("#pkg-table", DataTable)
            table.focus()
            await pilot.pause()

            assert "fzf" in _visible_packages(table)
            await pilot.press("d")
            assert "fzf" not in _visible_packages(table)
            assert "git" in _visible_packages(table)
            await pilot.press("d")
            assert "fzf" in _visible_packages(table)


@pytest.mark.asyncio
async def test_dep_packages_not_refetched_on_filter_keystroke(tmp_config: Path, monkeypatch):
    calls = []

    def fake_dep_packages(self):
        calls.append(1)
        return {"fzf"}

    monkeypatch.setattr(SystemInfo, "list_installed_packages", lambda self: ["git", "fzf"])
    monkeypatch.setattr(SystemInfo, "list_dependency_packages", fake_dep_packages)

    with patch("socket.gethostname", return_value="testhost"):
        app = _HarnessApp(TTConfig(tmp_config), SystemInfo())
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, PackageScreen)
            assert len(calls) == 1  # only the initial on_mount load

            filter_input = screen.query_one("#pkg-filter")
            filter_input.focus()
            await pilot.press("g")
            await pilot.press("i")
            await pilot.press("t")

            assert len(calls) == 1  # unchanged — no subprocess call per keystroke


@pytest.mark.asyncio
async def test_show_package_info_runs_as_exclusive_worker(tmp_config: Path, monkeypatch):
    """Regression test: scrolling quickly through the package table spawns
    one _show_package_info worker per row passed through (RowHighlighted
    fires once per row). Without exclusive=True, those workers all run
    concurrently and race to write into the same #pkg-info RichLog."""
    captured: list[dict] = []
    original_run_worker = PackageScreen.run_worker

    def fake_run_worker(self, *args, **kwargs):
        captured.append(kwargs)
        return original_run_worker(self, *args, **kwargs)

    monkeypatch.setattr(PackageScreen, "run_worker", fake_run_worker)
    monkeypatch.setattr(SystemInfo, "list_installed_packages", lambda self: ["git", "fzf"])
    monkeypatch.setattr(SystemInfo, "list_dependency_packages", lambda self: set())

    with patch("socket.gethostname", return_value="testhost"):
        app = _HarnessApp(TTConfig(tmp_config), SystemInfo())
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, PackageScreen)
            screen._show_package_info("common", "git")
            await pilot.pause()

    assert captured, "run_worker was never called"
    assert captured[0].get("exclusive") is True


@pytest.mark.asyncio
async def test_page_down_and_page_up_work_regardless_of_focus(
    tmp_config_many_packages: Path, monkeypatch
):
    """Regression test: right after the screen mounts, the filter Input
    holds focus by default (it's first in DOM order). Input doesn't bind
    pageup/pagedown, so those keys must be handled at the screen level to
    do anything at all — this is the reported "PgDn/PgUp doesn't work"
    bug."""
    monkeypatch.setattr(SystemInfo, "list_installed_packages", lambda self: [])
    monkeypatch.setattr(SystemInfo, "list_dependency_packages", lambda self: set())

    with patch("socket.gethostname", return_value="testhost"):
        app = _HarnessApp(TTConfig(tmp_config_many_packages), SystemInfo())
        async with app.run_test(size=(80, 24)) as pilot:
            screen = app.screen
            assert isinstance(screen, PackageScreen)
            table = screen.query_one("#pkg-table", DataTable)
            filter_input = screen.query_one("#pkg-filter")

            assert filter_input.has_focus  # default focus, not explicitly moved
            assert table.row_count > 10  # enough rows for PageDown to matter

            before = table.cursor_row
            await pilot.press("pagedown")
            after_down = table.cursor_row
            assert after_down > before + 1  # moved by more than one row

            await pilot.press("pageup")
            after_up = table.cursor_row
            assert after_up < after_down
