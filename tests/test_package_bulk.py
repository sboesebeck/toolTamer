"""Tests for marking rows and bulk operations in PackageScreen."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from textual.app import App
from textual.widgets import DataTable, Label

from tui.core.config import TTConfig
from tui.core.system import SystemInfo
from tui.screens.packages import PackageScreen


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """common: git, fzf (both installed) — host: none. Plus an extra
    package that is installed but in no config."""
    base = tmp_path / "toolTamer"
    configs = base / "configs"
    common = configs / "common"
    common.mkdir(parents=True)
    (common / "files").mkdir()
    (common / "to_install.brew").write_text("git\nfzf\nvim\n")
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


def _mark_cell(table: DataTable, package: str) -> str:
    """Read back the mark column (index 0) for the row whose key ends
    with ':{package}'."""
    row_key = next(k for k in table.rows if str(k.value).endswith(f":{package}"))
    return str(table.get_row(row_key)[0])


def _row_index(table: DataTable, package: str) -> int:
    keys = [str(k.value) for k in table.rows]
    return next(i for i, k in enumerate(keys) if k.endswith(f":{package}"))


@pytest.mark.asyncio
async def test_space_toggles_mark_on_cursor_row(tmp_config: Path, monkeypatch):
    monkeypatch.setattr(
        SystemInfo, "list_installed_packages", lambda self: ["git", "fzf", "vim"]
    )
    monkeypatch.setattr(SystemInfo, "list_dependency_packages", lambda self: set())
    # Mounting triggers _load_extra_deps (get_required_by), and the
    # auto-highlighted first row triggers _show_package_info
    # (get_package_info/get_package_tap) — mock both so nothing here runs
    # a real subprocess against whatever's actually installed.
    monkeypatch.setattr(SystemInfo, "get_required_by", lambda self, pkg: [])
    monkeypatch.setattr(SystemInfo, "get_package_info", lambda self, pkg: "")
    monkeypatch.setattr(SystemInfo, "get_package_tap", lambda self, pkg: None)

    with patch("socket.gethostname", return_value="testhost"):
        app = _HarnessApp(TTConfig(tmp_config), SystemInfo())
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, PackageScreen)
            table = screen.query_one("#pkg-table", DataTable)

            column_labels = [str(c.label) for c in table.columns.values()]
            assert column_labels == ["✓", "St", "Package", "Dep", "Config"]

            table.focus()
            table.move_cursor(row=_row_index(table, "fzf"))
            await pilot.pause()

            assert _mark_cell(table, "fzf") == ""
            await pilot.press("space")
            assert _mark_cell(table, "fzf") == "✓"
            assert screen._marked == {"common:fzf"}
            # cursor must not jump away from the row just marked
            assert table.cursor_row == _row_index(table, "fzf")

            await pilot.press("space")
            assert _mark_cell(table, "fzf") == ""
            assert screen._marked == set()


@pytest.mark.asyncio
async def test_marks_survive_filtering(tmp_config: Path, monkeypatch):
    monkeypatch.setattr(
        SystemInfo, "list_installed_packages", lambda self: ["git", "fzf", "vim"]
    )
    monkeypatch.setattr(SystemInfo, "list_dependency_packages", lambda self: set())
    # Mounting triggers _load_extra_deps (get_required_by), and the
    # auto-highlighted first row triggers _show_package_info
    # (get_package_info/get_package_tap) — mock both so nothing here runs
    # a real subprocess against whatever's actually installed.
    monkeypatch.setattr(SystemInfo, "get_required_by", lambda self, pkg: [])
    monkeypatch.setattr(SystemInfo, "get_package_info", lambda self, pkg: "")
    monkeypatch.setattr(SystemInfo, "get_package_tap", lambda self, pkg: None)

    with patch("socket.gethostname", return_value="testhost"):
        app = _HarnessApp(TTConfig(tmp_config), SystemInfo())
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, PackageScreen)
            table = screen.query_one("#pkg-table", DataTable)
            table.focus()
            table.move_cursor(row=_row_index(table, "fzf"))
            await pilot.pause()
            await pilot.press("space")
            assert screen._marked == {"common:fzf"}

            # filter the marked row away and back again
            screen._load_packages(filter_text="git")
            assert "fzf" not in [str(k.value).split(":", 1)[1] for k in table.rows]
            screen._load_packages(filter_text="")
            assert screen._marked == {"common:fzf"}
            assert _mark_cell(table, "fzf") == "✓"


@pytest.mark.asyncio
async def test_title_shows_marked_count(tmp_config: Path, monkeypatch):
    monkeypatch.setattr(
        SystemInfo, "list_installed_packages", lambda self: ["git", "fzf", "vim"]
    )
    monkeypatch.setattr(SystemInfo, "list_dependency_packages", lambda self: set())
    # Mounting triggers _load_extra_deps (get_required_by), and the
    # auto-highlighted first row triggers _show_package_info
    # (get_package_info/get_package_tap) — mock both so nothing here runs
    # a real subprocess against whatever's actually installed.
    monkeypatch.setattr(SystemInfo, "get_required_by", lambda self, pkg: [])
    monkeypatch.setattr(SystemInfo, "get_package_info", lambda self, pkg: "")
    monkeypatch.setattr(SystemInfo, "get_package_tap", lambda self, pkg: None)

    with patch("socket.gethostname", return_value="testhost"):
        app = _HarnessApp(TTConfig(tmp_config), SystemInfo())
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, PackageScreen)
            table = screen.query_one("#pkg-table", DataTable)
            title = screen.query_one("#pkg-title", Label)
            table.focus()
            await pilot.pause()

            assert "marked" not in str(title.renderable)

            table.move_cursor(row=_row_index(table, "git"))
            await pilot.pause()
            await pilot.press("space")
            assert "(1 marked)" in str(title.renderable)

            table.move_cursor(row=_row_index(table, "vim"))
            await pilot.pause()
            await pilot.press("space")
            assert "(2 marked)" in str(title.renderable)

            await pilot.press("space")
            assert "(1 marked)" in str(title.renderable)


def _screen_with_rows(tmp_config: Path, monkeypatch, rows) -> PackageScreen:
    """Unmounted screen with a hand-built row cache — lets the
    precondition logic be tested without a full table render."""
    with patch("socket.gethostname", return_value="testhost"):
        screen = PackageScreen(TTConfig(tmp_config), SystemInfo())
    monkeypatch.setattr(PackageScreen, "app", MagicMock())
    screen.query_one = MagicMock()
    screen._all_rows = list(rows)
    # _run_bulk_action (and _run_pkg_action) call get_current_worker() —
    # needed for real when run as an actual @work worker, but calling the
    # method directly via .__wrapped__ (as the bulk-action tests below
    # do) bypasses Textual's worker machinery entirely, so without this
    # mock get_current_worker() raises NoActiveWorker.
    monkeypatch.setattr(
        "tui.screens.packages.get_current_worker",
        lambda: MagicMock(is_cancelled=False),
    )
    return screen


def _mixed_screen(tmp_config: Path, monkeypatch) -> PackageScreen:
    """One row per status: OK (in config), !! (in config), ++ (extra),
    -- (unknown install state)."""
    return _screen_with_rows(
        tmp_config,
        monkeypatch,
        [
            ("OK", "git", "common", "common:git", False),
            ("!!", "vim", "common", "common:vim", False),
            ("++", "wget", "system", "_extra_:wget", False),
            ("--", "bat", "common", "common:bat", False),
        ],
    )


def test_split_marked_for_uninstall(tmp_config: Path, monkeypatch):
    screen = _mixed_screen(tmp_config, monkeypatch)
    screen._marked = {"common:git", "common:vim", "_extra_:wget", "common:bat"}

    valid, skipped = screen._split_marked("uninstall")

    assert valid == [("common", "git"), ("_extra_", "wget")]
    assert skipped == [
        ("common", "vim", "not installed"),
        ("common", "bat", "not installed"),
    ]


def test_split_marked_for_move_and_remove(tmp_config: Path, monkeypatch):
    for action in ("move", "remove"):
        screen = _mixed_screen(tmp_config, monkeypatch)
        screen._marked = {"common:git", "common:vim", "_extra_:wget", "common:bat"}

        valid, skipped = screen._split_marked(action)

        assert valid == [
            ("common", "git"),
            ("common", "vim"),
            ("common", "bat"),
        ], action
        assert skipped == [("_extra_", "wget", "not in a config")], action


def test_split_marked_for_uninstall_and_remove(tmp_config: Path, monkeypatch):
    screen = _mixed_screen(tmp_config, monkeypatch)
    screen._marked = {"common:git", "common:vim", "_extra_:wget", "common:bat"}

    valid, skipped = screen._split_marked("uninstall_remove")

    assert valid == [("common", "git")]
    assert skipped == [
        ("common", "vim", "not installed"),
        ("_extra_", "wget", "not in a config"),
        ("common", "bat", "not installed"),
    ]


def test_split_marked_ignores_rows_hidden_by_filter_but_keeps_order(
    tmp_config: Path, monkeypatch
):
    """Marks reference rows by key, so the split works off the cached row
    list — independent of what is currently rendered — and reports rows in
    table order, not set order."""
    screen = _mixed_screen(tmp_config, monkeypatch)
    screen._marked = {"common:bat", "common:git", "gone:ghost"}

    valid, skipped = screen._split_marked("remove")

    assert valid == [("common", "git"), ("common", "bat")]
    assert skipped == []


@pytest.fixture
def marked_app(tmp_config: Path, monkeypatch):
    """App whose PackageScreen has git (OK) and vim (!!) marked.

    Mocks every SystemInfo method that mounting/highlighting can trigger a
    subprocess call for (_load_extra_deps's get_required_by, and
    _show_package_info's get_package_info/get_package_tap for whatever row
    ends up auto-highlighted) — otherwise these run for real against
    whatever's actually installed on the machine running the tests."""
    monkeypatch.setattr(
        SystemInfo, "list_installed_packages", lambda self: ["git", "fzf", "wget"]
    )
    monkeypatch.setattr(SystemInfo, "list_dependency_packages", lambda self: set())
    monkeypatch.setattr(SystemInfo, "get_required_by", lambda self, pkg: [])
    monkeypatch.setattr(SystemInfo, "get_package_info", lambda self, pkg: "")
    monkeypatch.setattr(SystemInfo, "get_package_tap", lambda self, pkg: None)
    with patch("socket.gethostname", return_value="testhost"):
        return _HarnessApp(TTConfig(tmp_config), SystemInfo())


@pytest.mark.asyncio
async def test_uninstall_key_opens_bulk_confirm_with_valid_and_skipped(marked_app):
    from tui.screens.packages import BulkActionConfirmScreen

    async with marked_app.run_test() as pilot:
        screen = marked_app.screen
        table = screen.query_one("#pkg-table", DataTable)
        table.focus()
        screen._marked = {"common:git", "common:vim"}
        await pilot.pause()

        await pilot.press("x")
        await pilot.pause()

        dialog = marked_app.screen
        assert isinstance(dialog, BulkActionConfirmScreen)
        assert dialog._valid == [("common", "git")]
        assert dialog._skipped == [("common", "vim", "not installed")]


@pytest.mark.asyncio
async def test_unmarked_uninstall_still_acts_on_cursor_row_only(marked_app, monkeypatch):
    """No behaviour change for the unmarked case: no dialog, straight to
    the existing single-package worker."""
    run_pkg = MagicMock()
    monkeypatch.setattr(PackageScreen, "_run_pkg_action", run_pkg)

    async with marked_app.run_test() as pilot:
        screen = marked_app.screen
        table = screen.query_one("#pkg-table", DataTable)
        table.focus()
        table.move_cursor(row=_row_index(table, "git"))
        await pilot.pause()

        await pilot.press("x")
        await pilot.pause()

        assert marked_app.screen is screen  # no modal was pushed
        run_pkg.assert_called_once_with("git", "uninstall")


@pytest.mark.asyncio
async def test_no_dialog_when_no_marked_row_is_valid(marked_app, monkeypatch):
    from tui.screens.packages import BulkActionConfirmScreen

    run_bulk = MagicMock()
    monkeypatch.setattr(PackageScreen, "_run_bulk_action", run_bulk)

    async with marked_app.run_test() as pilot:
        screen = marked_app.screen
        table = screen.query_one("#pkg-table", DataTable)
        table.focus()
        screen._marked = {"_extra_:wget"}  # ++ → not in a config
        await pilot.pause()

        await pilot.press("r")
        await pilot.pause()

        assert not isinstance(marked_app.screen, BulkActionConfirmScreen)
        run_bulk.assert_not_called()
        assert screen._marked == {"_extra_:wget"}  # nothing ran, marks kept


@pytest.mark.asyncio
async def test_confirming_bulk_uninstall_starts_worker(marked_app, monkeypatch):
    run_bulk = MagicMock()
    monkeypatch.setattr(PackageScreen, "_run_bulk_action", run_bulk)

    async with marked_app.run_test() as pilot:
        screen = marked_app.screen
        screen.query_one("#pkg-table", DataTable).focus()
        screen._marked = {"common:git", "common:vim"}
        await pilot.pause()

        await pilot.press("x")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        run_bulk.assert_called_once_with("uninstall", [("common", "git")], None)


@pytest.mark.asyncio
async def test_cancelling_bulk_clears_marks_and_runs_nothing(marked_app, monkeypatch):
    run_bulk = MagicMock()
    monkeypatch.setattr(PackageScreen, "_run_bulk_action", run_bulk)

    async with marked_app.run_test() as pilot:
        screen = marked_app.screen
        screen.query_one("#pkg-table", DataTable).focus()
        screen._marked = {"common:git", "common:vim"}
        await pilot.pause()

        await pilot.press("x")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        run_bulk.assert_not_called()
        assert screen._marked == set()


@pytest.mark.asyncio
async def test_bulk_move_asks_for_destination_once(marked_app, monkeypatch):
    from tui.screens._dest_picker import DestPickerScreen

    run_bulk = MagicMock()
    monkeypatch.setattr(PackageScreen, "_run_bulk_action", run_bulk)

    async with marked_app.run_test() as pilot:
        screen = marked_app.screen
        screen.query_one("#pkg-table", DataTable).focus()
        screen._marked = {"common:git", "common:fzf"}
        await pilot.pause()

        await pilot.press("m")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        picker = marked_app.screen
        assert isinstance(picker, DestPickerScreen)
        run_bulk.assert_not_called()  # nothing runs before a target is picked

        picker.dismiss("testhost")
        await pilot.pause()

        run_bulk.assert_called_once_with(
            "move", [("common", "fzf"), ("common", "git")], "testhost"
        )


@pytest.mark.asyncio
async def test_bulk_move_picker_does_not_write_its_own_label_as_a_package(
    marked_app,
):
    """Regression test: _BulkDestPickerScreen overrode
    on_option_list_option_selected by name to skip the base class's
    move_package() call and just return the destination — but Textual
    invokes on_<message> handlers from every class in the MRO that defines
    one, not only the most-derived one. So selecting an option here used
    to run *both* handlers: the override's dismiss() and the base
    DestPickerScreen's move_package(), which wrote the picker's own
    "N marked package(s)" label into the destination config file as if it
    were a real package name. Exercise a real OptionList selection (not
    picker.dismiss(...) called directly, which only tests the callback and
    never touches on_option_list_option_selected at all)."""
    from textual.widgets import OptionList

    async with marked_app.run_test() as pilot:
        screen = marked_app.screen
        screen.query_one("#pkg-table", DataTable).focus()
        screen._marked = {"common:git", "common:fzf"}
        await pilot.pause()

        await pilot.press("m")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        ol = marked_app.screen.query_one(OptionList)
        ol.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        # The real (unmocked) _run_bulk_action worker is now running in
        # the background — wait for it to finish before the app tears
        # down and we read the file it's writing to, instead of leaving
        # an unjoined thread racing the assertion below.
        await marked_app.workers.wait_for_complete()

    host_file = (
        screen._tt_config.configs_dir / "testhost" / "to_install.brew"
    )
    contents = host_file.read_text() if host_file.exists() else ""
    assert "marked package(s)" not in contents, contents


def _logged_texts(screen: PackageScreen) -> list[str]:
    """Plain text of every Text object passed to log.write via
    call_from_thread(log.write, Text(...))."""
    texts = []
    for call in screen.app.call_from_thread.call_args_list:
        args = call.args
        if len(args) == 2 and hasattr(args[1], "plain"):
            texts.append(args[1].plain)
    return texts


def _marked_was_cleared(screen: PackageScreen) -> bool:
    """screen.app is a bare MagicMock in these .__wrapped__ tests, so
    call_from_thread(self._marked.clear) is recorded but never actually
    invoked — check the call happened instead of asserting on
    screen._marked directly."""
    return any(
        call.args == (screen._marked.clear,)
        for call in screen.app.call_from_thread.call_args_list
    )


def test_bulk_uninstall_continues_after_a_failure(tmp_config: Path, monkeypatch):
    screen = _mixed_screen(tmp_config, monkeypatch)
    screen._marked = {"common:git", "common:bat"}
    monkeypatch.setattr(
        screen._system,
        "get_required_by",
        lambda pkg: ["gnome-control-center"] if pkg == "git" else [],
    )
    uninstall = MagicMock(return_value=(True, "done"))
    monkeypatch.setattr(screen._system, "uninstall_package", uninstall)

    PackageScreen._run_bulk_action.__wrapped__(
        screen, "uninstall", [("common", "git"), ("common", "bat")], None
    )

    # git is blocked by the required-by pre-check, bat still gets processed
    uninstall.assert_called_once_with("bat")
    texts = _logged_texts(screen)
    assert any("✗ git" in t and "gnome-control-center" in t for t in texts), texts
    assert "✓ bat" in texts, texts
    assert any("1 done, 1 skipped/failed." in t for t in texts), texts
    assert _marked_was_cleared(screen)


def test_bulk_uninstall_reports_package_manager_failure(tmp_config: Path, monkeypatch):
    screen = _mixed_screen(tmp_config, monkeypatch)
    monkeypatch.setattr(screen._system, "get_required_by", lambda pkg: [])
    monkeypatch.setattr(
        screen._system, "uninstall_package", lambda pkg: (False, "Error: no such keg")
    )

    PackageScreen._run_bulk_action.__wrapped__(
        screen, "uninstall", [("common", "git")], None
    )

    texts = _logged_texts(screen)
    assert any("✗ git" in t and "no such keg" in t for t in texts), texts


def test_bulk_uninstall_and_remove_drops_config_entry_only_on_success(
    tmp_config: Path, monkeypatch
):
    screen = _mixed_screen(tmp_config, monkeypatch)
    screen._marked = {"common:git", "common:fzf"}
    # git uninstalls fine, fzf is required by something else
    monkeypatch.setattr(
        screen._system,
        "get_required_by",
        lambda pkg: ["some-other-pkg"] if pkg == "fzf" else [],
    )
    monkeypatch.setattr(screen._system, "uninstall_package", lambda pkg: (True, "ok"))

    PackageScreen._run_bulk_action.__wrapped__(
        screen, "uninstall_remove", [("common", "git"), ("common", "fzf")], None
    )

    pkg_file = tmp_config / "configs" / "common" / "to_install.brew"
    remaining = pkg_file.read_text().split()
    assert "git" not in remaining  # uninstalled → also dropped from config
    assert "fzf" in remaining  # uninstall failed → config entry kept

    texts = _logged_texts(screen)
    assert "✓ git" in texts, texts
    assert any(
        "✗ fzf" in t and "kept in config" in t and "some-other-pkg" in t
        for t in texts
    ), texts
    assert _marked_was_cleared(screen)


def test_bulk_remove_from_config_drops_every_entry(tmp_config: Path, monkeypatch):
    screen = _mixed_screen(tmp_config, monkeypatch)
    screen._marked = {"common:git", "common:vim"}
    uninstall = MagicMock()
    monkeypatch.setattr(screen._system, "uninstall_package", uninstall)

    PackageScreen._run_bulk_action.__wrapped__(
        screen, "remove", [("common", "git"), ("common", "vim")], None
    )

    remaining = (tmp_config / "configs" / "common" / "to_install.brew").read_text().split()
    assert remaining == ["fzf"]
    uninstall.assert_not_called()  # config-only operation
    assert _logged_texts(screen).count("✓ git") == 1
    assert _marked_was_cleared(screen)


def test_bulk_move_uses_the_single_destination_for_all_packages(
    tmp_config: Path, monkeypatch
):
    screen = _mixed_screen(tmp_config, monkeypatch)
    screen._marked = {"common:git", "common:fzf"}

    PackageScreen._run_bulk_action.__wrapped__(
        screen, "move", [("common", "git"), ("common", "fzf")], "testhost"
    )

    common = (tmp_config / "configs" / "common" / "to_install.brew").read_text().split()
    host = (tmp_config / "configs" / "testhost" / "to_install.brew").read_text().split()
    assert common == ["vim"]
    assert sorted(host) == ["fzf", "git"]
    assert _marked_was_cleared(screen)


@pytest.mark.asyncio
async def test_u_without_marks_confirms_for_the_cursor_row(marked_app, monkeypatch):
    from tui.screens.packages import BulkActionConfirmScreen

    run_bulk = MagicMock()
    monkeypatch.setattr(PackageScreen, "_run_bulk_action", run_bulk)

    async with marked_app.run_test() as pilot:
        screen = marked_app.screen
        table = screen.query_one("#pkg-table", DataTable)
        table.focus()
        table.move_cursor(row=_row_index(table, "git"))
        await pilot.pause()

        await pilot.press("u")
        await pilot.pause()

        dialog = marked_app.screen
        assert isinstance(dialog, BulkActionConfirmScreen)
        assert dialog._valid == [("common", "git")]
        assert dialog._skipped == []

        await pilot.press("y")
        await pilot.pause()
        run_bulk.assert_called_once_with(
            "uninstall_remove", [("common", "git")], None
        )


@pytest.mark.asyncio
async def test_u_on_an_extra_package_is_rejected_without_a_dialog(
    marked_app, monkeypatch
):
    from tui.screens.packages import BulkActionConfirmScreen

    run_bulk = MagicMock()
    monkeypatch.setattr(PackageScreen, "_run_bulk_action", run_bulk)

    async with marked_app.run_test() as pilot:
        screen = marked_app.screen
        table = screen.query_one("#pkg-table", DataTable)
        table.focus()
        table.move_cursor(row=_row_index(table, "wget"))  # ++ / _extra_
        await pilot.pause()

        await pilot.press("u")
        await pilot.pause()

        assert not isinstance(marked_app.screen, BulkActionConfirmScreen)
        run_bulk.assert_not_called()
