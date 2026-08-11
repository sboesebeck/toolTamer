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
from textual.widgets import Label

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
    # A per-selector mock (not one bare MagicMock for every call) so tests
    # can tell a "#pkg-count" update apart from a "#file-count" one —
    # both labels' text can contain "managed", so filtering call_from_thread
    # calls by content alone isn't enough once there's more than one update
    # per label (the background refinement writes a second #pkg-count
    # update after the fast pass).
    labels: dict[str, MagicMock] = {}

    def fake_query_one(selector, *_args, **_kwargs):
        return labels.setdefault(selector, MagicMock())

    status_bar.query_one = MagicMock(side_effect=fake_query_one)
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


def _pkg_count_texts(status_bar: StatusBar) -> list[str]:
    """Every text passed to the '#pkg-count' Label.update via
    call_from_thread, in call order — the fast pass writes one, the
    background refinement (if it runs at all) writes a second, final
    one."""
    target = status_bar.query_one("#pkg-count", Label).update
    return [
        str(call.args[1])
        for call in status_bar.app.call_from_thread.call_args_list
        if len(call.args) == 2 and call.args[0] == target
    ]


def _pkg_count_text(status_bar: StatusBar) -> str:
    """The first text passed to the '#pkg-count' Label.update."""
    texts = _pkg_count_texts(status_bar)
    if not texts:
        raise AssertionError("pkg-count update was never sent")
    return texts[0]


def test_extra_count_excludes_dependency_installed_packages(
    tmp_config: Path, monkeypatch
):
    """A package not tracked in any config still isn't "extra" if it was
    installed as a dependency (list_dependency_packages) — it's an expected
    side effect of installing something that *is* tracked, not unmanaged
    clutter. Deliberately checked via the cheap, single-call
    list_dependency_packages() rather than a per-package get_required_by()
    call: this scan reruns on every dashboard visit and must stay to a
    fixed number of subprocess calls regardless of how many extra packages
    are installed (get_required_by per package hung the real test suite —
    see test_dashboard.py, which doesn't mock SystemInfo)."""
    status_bar = _make_status_bar(tmp_config, monkeypatch)
    fake_worker = MagicMock(is_cancelled=False)
    monkeypatch.setattr(
        "tui.widgets.status_bar.get_current_worker", lambda: fake_worker
    )
    monkeypatch.setattr(
        status_bar._system, "list_installed_packages",
        lambda: ["git", "json-glib"],
    )
    monkeypatch.setattr(
        status_bar._system, "list_dependency_packages",
        lambda: {"json-glib"},
    )
    required_by = MagicMock()
    monkeypatch.setattr(status_bar._system, "get_required_by", required_by)

    StatusBar._scan_status.__wrapped__(status_bar)

    assert "extra" not in _pkg_count_text(status_bar)
    required_by.assert_not_called()  # bounded cost: no per-package lookups


def test_scan_status_refines_the_extra_count_in_the_background(
    tmp_config: Path, monkeypatch
):
    """Regression test for the "im Hauptmenü stimmt die Zahl nicht"
    report: the cheap list_dependency_packages() signal misses json-glib
    (same fixture as the package-screen equivalent), so the fast pass
    counts it as "extra" — the background refinement (get_required_by,
    the same structural check the package screen uses) must then correct
    that down to 0 in a second update, not leave the stale fast number
    standing forever."""
    status_bar = _make_status_bar(tmp_config, monkeypatch)
    fake_worker = MagicMock(is_cancelled=False)
    monkeypatch.setattr(
        "tui.widgets.status_bar.get_current_worker", lambda: fake_worker
    )
    monkeypatch.setattr(
        status_bar._system, "list_installed_packages",
        lambda: ["git", "json-glib"],
    )
    monkeypatch.setattr(status_bar._system, "list_dependency_packages", lambda: set())
    monkeypatch.setattr(
        status_bar._system, "get_required_by",
        lambda pkg: ["gnome-control-center"] if pkg == "json-glib" else [],
    )

    StatusBar._scan_status.__wrapped__(status_bar)

    texts = _pkg_count_texts(status_bar)
    assert len(texts) == 2, texts  # fast pass, then the refined one
    assert "1 extra" in texts[0] and "refining" in texts[0].lower(), texts[0]
    assert "extra" not in texts[1], texts[1]  # refined away — json-glib is a dependency


def test_scan_status_refinement_skipped_when_nothing_is_excess(
    tmp_config: Path, monkeypatch
):
    """No excess packages at all → no point spinning up the thread pool
    for zero candidates."""
    status_bar = _make_status_bar(tmp_config, monkeypatch)
    fake_worker = MagicMock(is_cancelled=False)
    monkeypatch.setattr(
        "tui.widgets.status_bar.get_current_worker", lambda: fake_worker
    )
    monkeypatch.setattr(
        status_bar._system, "list_installed_packages", lambda: ["git"]
    )
    monkeypatch.setattr(status_bar._system, "list_dependency_packages", lambda: set())
    required_by = MagicMock()
    monkeypatch.setattr(status_bar._system, "get_required_by", required_by)

    StatusBar._scan_status.__wrapped__(status_bar)

    required_by.assert_not_called()
    assert len(_pkg_count_texts(status_bar)) == 1  # just the one, non-refining pass


def test_tap_qualified_entries_are_not_counted_missing_or_extra(
    tmp_path: Path, monkeypatch
):
    """Regression: the config names a tap package fully qualified
    (forketyfork/tap/clawtunes) while brew lists it short (clawtunes).
    Comparing naively counted it BOTH as missing (it's in the config but
    "not installed") and as extra (installed but "not in any config")."""
    base = tmp_path / "toolTamer"
    common = base / "configs" / "common"
    common.mkdir(parents=True)
    (common / "files").mkdir()
    (common / "to_install.brew").write_text("git\nforketyfork/tap/clawtunes\n")
    (common / "files.conf").write_text("")
    host = base / "configs" / "testhost"
    host.mkdir(parents=True)
    (host / "files").mkdir()
    (host / "files.conf").write_text("")
    (host / "includes.conf").write_text("")
    (base / "tt.conf").write_text("")

    monkeypatch.setattr("socket.gethostname", lambda: "testhost")
    system = SystemInfo()
    monkeypatch.setattr(
        system, "list_installed_packages", lambda: ["git", "clawtunes"]
    )
    monkeypatch.setattr(system, "list_dependency_packages", lambda: set())
    monkeypatch.setattr(system, "get_required_by", lambda pkg: [])

    status_bar = StatusBar(TTConfig(base), system)
    monkeypatch.setattr(StatusBar, "app", MagicMock())
    labels: dict[str, MagicMock] = {}
    status_bar.query_one = MagicMock(
        side_effect=lambda sel, *a, **kw: labels.setdefault(sel, MagicMock())
    )
    monkeypatch.setattr(
        "tui.widgets.status_bar.get_current_worker",
        lambda: MagicMock(is_cancelled=False),
    )

    StatusBar._scan_status.__wrapped__(status_bar)

    text = _pkg_count_text(status_bar)
    assert "missing" not in text, text
    assert "extra" not in text, text
    assert "all synced" in text, text
