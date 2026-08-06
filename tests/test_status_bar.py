"""Regression test: StatusBar._scan_status must not touch its widgets once
its worker has been cancelled (e.g. the dashboard screen was popped while a
scan was still running in the background thread — Textual auto-cancels a
widget's workers on unmount via Widget._on_unmount -> workers.cancel_node).

Without a cancellation check, the worker keeps running the full scan
regardless and then calls query_one() on widgets that may no longer be
mounted, raising NoMatches. This showed up as an intermittent
test_dashboard.py failure ("NoMatches: No nodes match '#file-details' on
StatusBar()") — a leftover scan from an earlier test's StatusBar still
running when a later test's app was already tearing down.

Testing this directly, bypassing the thread/worker machinery, is far more
reliable than racing a real background thread against Textual's widget
removal — the `@work` decorator preserves the original method via
`__wrapped__` (functools.wraps), so the cancellation-guard logic can be
exercised synchronously and deterministically.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tui.core.config import TTConfig
from tui.core.system import SystemInfo
from tui.widgets.status_bar import StatusBar


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


def _make_status_bar(tmp_config: Path, monkeypatch) -> StatusBar:
    monkeypatch.setattr(SystemInfo, "list_installed_packages", lambda self: [])
    monkeypatch.setattr("socket.gethostname", lambda: "testhost")
    tt_config = TTConfig(tmp_config)
    system = SystemInfo()
    status_bar = StatusBar(tt_config, system)
    # Not mounted in an app — app/query_one are mocked directly below, since
    # this test exercises _scan_status's own control flow, not Textual's
    # widget tree. `app` is a read-only property on the base Widget class,
    # so it's replaced on the class (via monkeypatch, auto-reverted after
    # the test) rather than assigned on the instance.
    monkeypatch.setattr(StatusBar, "app", MagicMock())
    status_bar.query_one = MagicMock()
    return status_bar


def test_scan_status_skips_widget_updates_when_worker_cancelled(tmp_config: Path, monkeypatch):
    status_bar = _make_status_bar(tmp_config, monkeypatch)
    fake_worker = MagicMock(is_cancelled=True)
    monkeypatch.setattr(
        "tui.widgets.status_bar.get_current_worker", lambda: fake_worker
    )

    StatusBar._scan_status.__wrapped__(status_bar)

    status_bar.query_one.assert_not_called()
    status_bar.app.call_from_thread.assert_not_called()


def test_scan_status_updates_widgets_when_worker_not_cancelled(tmp_config: Path, monkeypatch):
    status_bar = _make_status_bar(tmp_config, monkeypatch)
    fake_worker = MagicMock(is_cancelled=False)
    monkeypatch.setattr(
        "tui.widgets.status_bar.get_current_worker", lambda: fake_worker
    )

    StatusBar._scan_status.__wrapped__(status_bar)

    # Sanity check the guard isn't unconditionally skipping everything —
    # the normal (not cancelled) path still does its job.
    assert status_bar.app.call_from_thread.call_count == 4  # pkg-count, pkg-details, file-count, file-details
