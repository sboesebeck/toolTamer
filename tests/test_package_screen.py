"""Tests for the Dep column, caching, and hide-toggle in PackageScreen."""

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
    """Read back the 'Package' column (index 2) for every currently
    visible row, in display order."""
    return [str(table.get_row(row_key)[2]) for row_key in table.rows]


def _dep_cell(table: DataTable, package: str) -> str:
    """Read back the 'Dep' column (index 3) for the row whose key ends
    with ':{package}'."""
    row_key = next(k for k in table.rows if str(k.value).endswith(f":{package}"))
    return str(table.get_row(row_key)[3])


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
            assert column_labels == ["✓", "St", "Package", "Dep", "Config"]

            assert _dep_cell(table, "git") == ""
            assert _dep_cell(table, "fzf") == "D"


@pytest.mark.asyncio
async def test_dep_column_also_marks_untracked_extras_required_by_something(
    tmp_config: Path, monkeypatch
):
    """Regression test: json-glib is installed, in no tracked config (shows
    as "++" extra), and missing from list_dependency_packages() (apt's
    "auto" install-reason flag missed it) — but it IS structurally required
    by another installed package. The overview must not let it look like a
    standalone extra tool the user can freely remove; the detail pane
    already flags this (get_required_by), the overview needs to match."""
    monkeypatch.setattr(
        SystemInfo, "list_installed_packages",
        lambda self: ["git", "fzf", "json-glib"],
    )
    monkeypatch.setattr(SystemInfo, "list_dependency_packages", lambda self: set())
    monkeypatch.setattr(
        SystemInfo, "get_required_by",
        lambda self, pkg: ["gnome-control-center"] if pkg == "json-glib" else [],
    )

    with patch("socket.gethostname", return_value="testhost"):
        app = _HarnessApp(TTConfig(tmp_config), SystemInfo())
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, PackageScreen)
            table = screen.query_one("#pkg-table", DataTable)

            # The extras check runs as a background worker (see
            # PackageScreen._load_extra_deps) precisely so opening the
            # screen doesn't block on it — wait for it here instead.
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert _dep_cell(table, "json-glib") == "D"


@pytest.mark.asyncio
async def test_title_shows_scanning_indicator_while_extra_deps_runs(
    tmp_config: Path, monkeypatch
):
    """Regression test: while the background extras scan is still
    running, a blank "Dep" cell must not read as "confirmed not a
    dependency" — the title shows an explicit indicator instead, cleared
    once the scan (and the merge that follows it) completes."""
    import asyncio
    import time

    monkeypatch.setattr(
        SystemInfo, "list_installed_packages",
        lambda self: ["git", "fzf", "json-glib"],
    )
    monkeypatch.setattr(SystemInfo, "list_dependency_packages", lambda self: set())

    def slow_required_by(self, pkg):
        time.sleep(0.1)
        return ["gnome-control-center"]

    monkeypatch.setattr(SystemInfo, "get_required_by", slow_required_by)

    with patch("socket.gethostname", return_value="testhost"):
        app = _HarnessApp(TTConfig(tmp_config), SystemInfo())
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, PackageScreen)
            title = screen.query_one("#pkg-title", Label)
            assert "checking" in str(title.renderable).lower(), title.renderable

            # Not app.workers.wait_for_complete(): the auto-highlighted
            # first row's _show_package_info worker is a *different*,
            # unrelated worker that's expected to end up cancelled here
            # (nothing consumes its result) — wait_for_complete() raises
            # WorkerCancelled for it regardless. Poll the title instead.
            for _ in range(30):
                await asyncio.sleep(0.02)
                await pilot.pause()
                if "checking" not in str(title.renderable).lower():
                    break
            else:
                pytest.fail(f"scanning indicator never cleared: {title.renderable}")


def test_extra_required_by_check_skips_tracked_packages(tmp_config: Path, monkeypatch):
    """The required-by check for the overview's "D" tag is a subprocess
    call per package — bounded to the (usually small) set of untracked
    "extra" packages, not run for every tracked package in the list.

    Exercises _extra_required_deps() directly on an unmounted screen
    (same pattern as _make_package_screen below) rather than through a
    live app: mounting also auto-highlights the first row, which triggers
    the *separate* detail-pane required-by check (_show_package_info) for
    whatever package that happens to be — a real and intentional call,
    but not the one this test is about, and asserting an exact global
    call list would make the test depend on table sort order."""
    calls = []

    def fake_required_by(pkg):
        calls.append(pkg)
        return []

    with patch("socket.gethostname", return_value="testhost"):
        screen = PackageScreen(TTConfig(tmp_config), SystemInfo())
    monkeypatch.setattr(
        screen._system, "list_installed_packages",
        lambda: ["git", "fzf", "json-glib"],
    )
    monkeypatch.setattr(screen._system, "get_required_by", fake_required_by)

    screen._extra_required_deps()

    assert calls == ["json-glib"]  # git/fzf are tracked in "common"


def test_extra_required_deps_runs_checks_concurrently(tmp_config: Path, monkeypatch):
    """Regression test: sequential per-package get_required_by() calls
    made this take minutes on a real machine with hundreds of untracked
    packages (the "100e ... werden als extra angezeigt" report). Proves
    actual concurrency (not just correctness, which a sequential loop
    would also satisfy) by tracking how many calls are in flight at once
    — must exceed 1, which a one-at-a-time loop could never do regardless
    of how this assertion is timed."""
    import threading
    import time

    with patch("socket.gethostname", return_value="testhost"):
        screen = PackageScreen(TTConfig(tmp_config), SystemInfo())
    extras = [f"extra-pkg-{i}" for i in range(10)]
    monkeypatch.setattr(
        screen._system, "list_installed_packages", lambda: ["git", "fzf"] + extras
    )
    lock = threading.Lock()
    in_flight = 0
    max_in_flight = 0

    def fake_required_by(pkg):
        nonlocal in_flight, max_in_flight
        with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        time.sleep(0.05)
        with lock:
            in_flight -= 1
        return []

    monkeypatch.setattr(screen._system, "get_required_by", fake_required_by)

    screen._extra_required_deps()

    assert max_in_flight > 1, "calls never overlapped — still running sequentially"


def test_extra_required_deps_checks_every_extra_and_finds_the_right_subset(
    tmp_config: Path, monkeypatch
):
    with patch("socket.gethostname", return_value="testhost"):
        screen = PackageScreen(TTConfig(tmp_config), SystemInfo())
    extras = [f"extra-pkg-{i}" for i in range(20)]
    monkeypatch.setattr(
        screen._system, "list_installed_packages", lambda: ["git", "fzf"] + extras
    )
    required = set(extras[:5])
    calls = []

    def fake_required_by(pkg):
        calls.append(pkg)
        return ["something"] if pkg in required else []

    monkeypatch.setattr(screen._system, "get_required_by", fake_required_by)

    found = screen._extra_required_deps()

    assert found == required
    assert sorted(calls) == sorted(extras)  # every extra got checked exactly once
    assert len(calls) == len(set(calls))


def test_extra_required_deps_stops_early_without_checking_every_extra(
    tmp_config: Path, monkeypatch
):
    """should_stop lets a still-running scan bail out as soon as it's
    superseded (e.g. hide-deps toggled again, another refresh triggered)
    instead of waiting for every remaining package to be checked —
    verified by a real early exit (fewer calls than extras), not just
    that the callback gets invoked."""
    import time

    with patch("socket.gethostname", return_value="testhost"):
        screen = PackageScreen(TTConfig(tmp_config), SystemInfo())
    extras = [f"extra-pkg-{i}" for i in range(20)]
    monkeypatch.setattr(
        screen._system, "list_installed_packages", lambda: ["git", "fzf"] + extras
    )
    calls = []

    def fake_required_by(pkg):
        time.sleep(0.02)  # gives the main thread a chance to observe and stop
        calls.append(pkg)
        return []

    monkeypatch.setattr(screen._system, "get_required_by", fake_required_by)

    stop_after = 2

    def should_stop():
        return len(calls) >= stop_after

    screen._extra_required_deps(should_stop=should_stop)

    assert len(calls) < len(extras)


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
async def test_extra_required_by_not_rechecked_on_filter_keystroke(
    tmp_config: Path, monkeypatch
):
    calls = []

    def fake_required_by(self, pkg):
        calls.append(pkg)
        return []

    monkeypatch.setattr(
        SystemInfo, "list_installed_packages",
        lambda self: ["git", "fzf", "json-glib"],
    )
    monkeypatch.setattr(SystemInfo, "list_dependency_packages", lambda self: set())
    monkeypatch.setattr(SystemInfo, "get_required_by", fake_required_by)

    with patch("socket.gethostname", return_value="testhost"):
        app = _HarnessApp(TTConfig(tmp_config), SystemInfo())
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, PackageScreen)
            await app.workers.wait_for_complete()
            await pilot.pause()
            # Not an exact call list: mounting also auto-highlights the
            # first row, which triggers the separate detail-pane
            # required-by check for that package — a real, unrelated call.
            # "json-glib" itself must appear exactly once, from the
            # initial extras scan.
            assert calls.count("json-glib") == 1
            assert "git" not in calls  # tracked, never checked by either path

            filter_input = screen.query_one("#pkg-filter")
            filter_input.focus()
            await pilot.press("g")
            await pilot.press("i")
            await pilot.press("t")

            assert calls.count("json-glib") == 1  # unchanged — no recheck per keystroke


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


def _make_package_screen(tmp_config: Path, monkeypatch) -> PackageScreen:
    with patch("socket.gethostname", return_value="testhost"):
        screen = PackageScreen(TTConfig(tmp_config), SystemInfo())
    # Not mounted — app/query_one are mocked directly, since this test
    # exercises _show_package_info's own cancellation control flow, not
    # Textual's widget tree. `app` is a read-only property on the base
    # Widget class, so it's replaced on the class (monkeypatch reverts it
    # automatically) rather than assigned on the instance.
    monkeypatch.setattr(PackageScreen, "app", MagicMock())
    screen.query_one = MagicMock()
    return screen


def test_show_package_info_stops_before_second_subprocess_call_when_cancelled(
    tmp_config: Path, monkeypatch
):
    """Regression test: exclusive=True alone does not stop an in-flight
    thread worker — Worker.cancel() only sets a flag, it never joins or
    kills the thread (verified against textual/worker.py). Without an
    is_cancelled check, a worker superseded by a newer one (e.g. the user
    already scrolled to the next row) keeps running to completion anyway,
    including get_package_tap's subprocess call and every RichLog write —
    this is exactly what produced "every row scrolled past gets displayed,
    one after another" once the key was released."""
    screen = _make_package_screen(tmp_config, monkeypatch)
    fake_worker = MagicMock(is_cancelled=True)
    monkeypatch.setattr(
        "tui.screens.packages.get_current_worker", lambda: fake_worker
    )
    get_info = MagicMock(return_value="some info")
    get_tap = MagicMock(return_value=None)
    monkeypatch.setattr(screen._system, "get_package_info", get_info)
    monkeypatch.setattr(screen._system, "get_package_tap", get_tap)

    PackageScreen._show_package_info.__wrapped__(screen, "common", "git")

    get_info.assert_called_once()  # first call always happens — no way to
    # know in advance it'll be stale before making it
    get_tap.assert_not_called()  # second call skipped once cancelled
    screen.query_one.assert_not_called()  # RichLog never touched
    screen.app.call_from_thread.assert_not_called()


def test_show_package_info_completes_when_not_cancelled(tmp_config: Path, monkeypatch):
    screen = _make_package_screen(tmp_config, monkeypatch)
    fake_worker = MagicMock(is_cancelled=False)
    monkeypatch.setattr(
        "tui.screens.packages.get_current_worker", lambda: fake_worker
    )
    monkeypatch.setattr(screen._system, "get_package_info", lambda pkg: "some info")
    monkeypatch.setattr(screen._system, "get_package_tap", lambda pkg: None)
    monkeypatch.setattr(screen._system, "list_installed_packages", lambda: [])

    PackageScreen._show_package_info.__wrapped__(screen, "common", "git")

    # Sanity check the guard isn't unconditionally skipping everything —
    # the normal (not cancelled) path still writes to the log.
    assert screen.app.call_from_thread.call_count > 0


def test_show_package_info_warns_when_required_by_something_installed(
    tmp_config: Path, monkeypatch
):
    """Regression test for the json-glib report: a package can be missing
    from list_dependency_packages() (no "D" tag) and still be structurally
    required by another installed package. That must be visible in the
    detail pane *before* the user tries x/u, not only surface as a failure
    message after the fact."""
    screen = _make_package_screen(tmp_config, monkeypatch)
    fake_worker = MagicMock(is_cancelled=False)
    monkeypatch.setattr(
        "tui.screens.packages.get_current_worker", lambda: fake_worker
    )
    monkeypatch.setattr(screen._system, "get_package_info", lambda pkg: "some info")
    monkeypatch.setattr(screen._system, "get_package_tap", lambda pkg: None)
    monkeypatch.setattr(
        screen._system, "list_installed_packages", lambda: ["json-glib"]
    )
    monkeypatch.setattr(
        screen._system,
        "get_required_by",
        lambda pkg: ["gnome-control-center"],
    )

    PackageScreen._show_package_info.__wrapped__(screen, "common", "json-glib")

    texts = _logged_texts(screen)
    assert any(
        "required by" in t.lower() and "gnome-control-center" in t for t in texts
    ), texts


def test_show_package_info_skips_required_by_check_when_not_installed(
    tmp_config: Path, monkeypatch
):
    """The required-by lookup is a subprocess call per package — skip it
    for packages that aren't even installed, where it can't apply."""
    screen = _make_package_screen(tmp_config, monkeypatch)
    fake_worker = MagicMock(is_cancelled=False)
    monkeypatch.setattr(
        "tui.screens.packages.get_current_worker", lambda: fake_worker
    )
    monkeypatch.setattr(screen._system, "get_package_info", lambda pkg: "some info")
    monkeypatch.setattr(screen._system, "get_package_tap", lambda pkg: None)
    monkeypatch.setattr(screen._system, "list_installed_packages", lambda: [])
    required_by = MagicMock(return_value=["something"])
    monkeypatch.setattr(screen._system, "get_required_by", required_by)

    PackageScreen._show_package_info.__wrapped__(screen, "common", "git")

    required_by.assert_not_called()


def _logged_texts(screen: PackageScreen) -> list[str]:
    """Plain text of every Text object passed to log.write via
    call_from_thread(log.write, Text(...))."""
    texts = []
    for call in screen.app.call_from_thread.call_args_list:
        args = call.args
        if len(args) == 2 and hasattr(args[1], "plain"):
            texts.append(args[1].plain)
    return texts


def test_uninstall_blocked_when_required_by_other_installed_package(
    tmp_config: Path, monkeypatch
):
    """Regression test for the json-glib report: a package can be missing
    from list_dependency_packages() (not "auto"-installed) and still be
    structurally required by another installed package. Uninstall must be
    pre-checked against that — via get_required_by(), a real reverse-
    dependency lookup — instead of just attempting the uninstall and
    dumping the package manager's raw error."""
    screen = _make_package_screen(tmp_config, monkeypatch)
    monkeypatch.setattr(
        "tui.screens.packages.get_current_worker",
        lambda: MagicMock(is_cancelled=False),
    )
    monkeypatch.setattr(
        screen._system, "get_required_by", lambda pkg: ["gnome-control-center"]
    )
    uninstall = MagicMock()
    monkeypatch.setattr(screen._system, "uninstall_package", uninstall)
    monkeypatch.setattr(screen, "_refresh_packages", MagicMock())

    PackageScreen._run_pkg_action.__wrapped__(screen, "json-glib", "uninstall")

    uninstall.assert_not_called()
    texts = _logged_texts(screen)
    assert any(
        "json-glib" in t and "gnome-control-center" in t for t in texts
    ), texts


def test_uninstall_proceeds_when_not_required_by_anything(
    tmp_config: Path, monkeypatch
):
    screen = _make_package_screen(tmp_config, monkeypatch)
    monkeypatch.setattr(
        "tui.screens.packages.get_current_worker",
        lambda: MagicMock(is_cancelled=False),
    )
    monkeypatch.setattr(screen._system, "get_required_by", lambda pkg: [])
    uninstall = MagicMock(return_value=(True, "done"))
    monkeypatch.setattr(screen._system, "uninstall_package", uninstall)
    monkeypatch.setattr(screen, "_refresh_packages", MagicMock())

    PackageScreen._run_pkg_action.__wrapped__(screen, "some-leaf-pkg", "uninstall")

    uninstall.assert_called_once_with("some-leaf-pkg")


def test_uninstall_proceeds_when_required_by_check_fails(
    tmp_config: Path, monkeypatch
):
    """get_required_by is a display-only lookup and must never block a
    real uninstall attempt just because the check itself failed."""
    screen = _make_package_screen(tmp_config, monkeypatch)
    monkeypatch.setattr(
        "tui.screens.packages.get_current_worker",
        lambda: MagicMock(is_cancelled=False),
    )

    def boom(pkg):
        raise RuntimeError("boom")

    monkeypatch.setattr(screen._system, "get_required_by", boom)
    uninstall = MagicMock(return_value=(True, "done"))
    monkeypatch.setattr(screen._system, "uninstall_package", uninstall)
    monkeypatch.setattr(screen, "_refresh_packages", MagicMock())

    PackageScreen._run_pkg_action.__wrapped__(screen, "some-pkg", "uninstall")

    uninstall.assert_called_once_with("some-pkg")


@pytest.mark.asyncio
async def test_pkg_action_workers_use_their_own_group(tmp_config: Path, monkeypatch):
    """Regression test: _run_pkg_action/_run_bulk_action must NOT share
    @work's default group ("default") with _show_package_info, which is
    exclusive=True there — otherwise highlighting a row while an
    install/uninstall/bulk action is still running would cancel it and
    silently drop the final refresh (same bug class as the "extra-deps"
    group fix for _load_extra_deps)."""
    captured: list[dict] = []
    original_run_worker = PackageScreen.run_worker

    def fake_run_worker(self, *args, **kwargs):
        captured.append(kwargs)
        return original_run_worker(self, *args, **kwargs)

    monkeypatch.setattr(PackageScreen, "run_worker", fake_run_worker)
    monkeypatch.setattr(SystemInfo, "list_installed_packages", lambda self: ["git"])
    monkeypatch.setattr(SystemInfo, "list_dependency_packages", lambda self: set())
    monkeypatch.setattr(SystemInfo, "get_required_by", lambda self, pkg: [])
    monkeypatch.setattr(
        SystemInfo, "uninstall_package", lambda self, pkg: (True, "done")
    )

    with patch("socket.gethostname", return_value="testhost"):
        app = _HarnessApp(TTConfig(tmp_config), SystemInfo())
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, PackageScreen)
            screen._dispatch_action(lambda: screen._run_pkg_action("git", "uninstall"))
            await pilot.pause()
            await app.workers.wait_for_complete()

    pkg_action_calls = [c for c in captured if c.get("group") == "pkg-action"]
    assert pkg_action_calls, captured
    assert not any(c.get("group", "default") == "default" for c in pkg_action_calls)


def test_dispatch_action_refuses_second_action_while_one_is_running(
    tmp_config: Path, monkeypatch
):
    """Regression test: _run_pkg_action/_run_bulk_action mutate config
    files (read-modify-write, no locking) and run real install/uninstall
    commands — a second one starting before the first finishes could race
    on the same config file or fire off duplicate uninstalls."""
    screen = _make_package_screen(tmp_config, monkeypatch)
    screen._action_busy = True
    worker_call = MagicMock()

    screen._dispatch_action(worker_call)

    worker_call.assert_not_called()
    # _dispatch_action runs on the main thread (it's what schedules the
    # worker in the first place), so the notice is written directly —
    # not via call_from_thread like everything inside the worker itself.
    written = [
        call.args[0].plain
        for call in screen.query_one.return_value.write.call_args_list
        if call.args and hasattr(call.args[0], "plain")
    ]
    assert any("still running" in t for t in written), written


def test_dispatch_action_runs_when_not_busy_and_sets_the_flag(
    tmp_config: Path, monkeypatch
):
    screen = _make_package_screen(tmp_config, monkeypatch)
    worker_call = MagicMock()

    screen._dispatch_action(worker_call)

    worker_call.assert_called_once()
    assert screen._action_busy is True


def test_finish_action_skips_refresh_but_still_clears_busy_when_cancelled(
    tmp_config: Path, monkeypatch
):
    """Regression test: Esc while an action is still running unmounts the
    screen and cancels its worker's flag, but must not crash the worker —
    _finish_action must skip the refresh (a fresh query_one, which raises
    NoMatches on an unmounted screen) while still clearing _action_busy."""
    screen = _make_package_screen(tmp_config, monkeypatch)
    # screen.app is a bare MagicMock (see _make_package_screen) — make its
    # call_from_thread actually invoke what it's given, like the real
    # thing does, so the effects below (_action_busy, _refresh_packages)
    # are observable instead of just recorded as unexecuted calls.
    screen.app.call_from_thread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
    screen._action_busy = True
    refresh = MagicMock()
    monkeypatch.setattr(screen, "_refresh_packages", refresh)
    cancelled_worker = MagicMock(is_cancelled=True)

    screen._finish_action(cancelled_worker)

    refresh.assert_not_called()
    assert screen._action_busy is False


def test_finish_action_refreshes_and_clears_busy_when_not_cancelled(
    tmp_config: Path, monkeypatch
):
    screen = _make_package_screen(tmp_config, monkeypatch)
    screen.app.call_from_thread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
    screen._action_busy = True
    refresh = MagicMock()
    monkeypatch.setattr(screen, "_refresh_packages", refresh)
    live_worker = MagicMock(is_cancelled=False)

    screen._finish_action(live_worker)

    refresh.assert_called_once()
    assert screen._action_busy is False


def test_refresh_packages_swallows_no_matches_from_an_unmounted_screen(
    tmp_config: Path, monkeypatch
):
    """Belt-and-suspenders: even if a worker's is_cancelled check and the
    actual unmount race (they aren't atomic), _refresh_packages itself
    must not propagate NoMatches back into the calling worker thread."""
    from textual.css.query import NoMatches

    screen = _make_package_screen(tmp_config, monkeypatch)
    screen.query_one.side_effect = NoMatches("no pkg-filter")

    screen._refresh_packages()  # must not raise
