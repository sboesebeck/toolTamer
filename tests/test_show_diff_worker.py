"""Regression test: FileScreen._show_diff must run as an exclusive worker.

Directory diffs can now spawn up to 10 `diff` subprocess calls; without
`exclusive=True`, rapid cursor movement across directory rows would queue
up multiple such workers writing into the same RichLog concurrently.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from textual.app import App
from textual.widgets import RichLog

from tui.core.config import TTConfig
from tui.core.system import SystemInfo
from tui.screens.files import FileScreen


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    base = tmp_path / "toolTamer"
    configs = base / "configs"
    common = configs / "common"
    common.mkdir(parents=True)
    (common / "files").mkdir()
    (common / "files.conf").write_text("zshrc;.zshrc\n")
    (common / "files" / "zshrc").write_text("hi\n")
    host = configs / "testhost"
    host.mkdir(parents=True)
    (host / "files").mkdir()
    (host / "files.conf").write_text("")
    (host / "includes.conf").write_text("")
    (base / "tt.conf").write_text("")
    return base


class _HarnessApp(App):
    """Minimal app whose only job is to host a FileScreen for the test."""

    def __init__(self, tt_config: TTConfig, system: SystemInfo):
        super().__init__()
        self._tt_config = tt_config
        self._system = system

    def on_mount(self) -> None:
        self.push_screen(FileScreen(self._tt_config, self._system))


@pytest.mark.asyncio
async def test_show_diff_runs_as_exclusive_worker(tmp_config: Path, monkeypatch):
    captured: list[dict] = []
    original_run_worker = FileScreen.run_worker

    def fake_run_worker(self, *args, **kwargs):
        captured.append(kwargs)
        return original_run_worker(self, *args, **kwargs)

    monkeypatch.setattr(FileScreen, "run_worker", fake_run_worker)

    with patch("socket.gethostname", return_value="testhost"):
        app = _HarnessApp(TTConfig(tmp_config), SystemInfo())
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, FileScreen)
            screen._show_diff("common", "zshrc", ".zshrc")
            await pilot.pause()

    assert captured, "run_worker was never called"
    assert captured[0].get("exclusive") is True


def _extract_log_text(log: RichLog) -> str:
    """RichLog stores rendered Strips, not plain text — join their plain
    text back together so assertions can search for substrings."""
    lines = []
    for strip in log.lines:
        lines.append("".join(segment.text for segment in strip))
    return "\n".join(lines)


@pytest.mark.asyncio
async def test_directory_diff_shows_inline_diff_for_changed_file(tmp_config: Path, monkeypatch):
    # Track a directory with one file that differs between "repo" and
    # "system" copies.
    common_files = tmp_config / "configs" / "common" / "files"
    tracked_dir = common_files / ".config" / "foo"
    tracked_dir.mkdir(parents=True)
    (tracked_dir / "bar.conf").write_text("old_value=1\n")
    (tmp_config / "configs" / "common" / "files.conf").write_text(
        "zshrc;.zshrc\n.config/foo;.config/foo\n"
    )

    fake_home = tmp_config.parent / "fake_home"
    (fake_home / ".config" / "foo").mkdir(parents=True)
    (fake_home / ".config" / "foo" / "bar.conf").write_text("old_value=2\n")

    with patch("socket.gethostname", return_value="testhost"), \
         patch.object(Path, "home", return_value=fake_home):
        app = _HarnessApp(TTConfig(tmp_config), SystemInfo())
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, FileScreen)
            worker = screen._show_diff("common", ".config/foo", ".config/foo")
            await worker.wait()
            await pilot.pause()

            text = _extract_log_text(screen.query_one("#file-diff", RichLog))

    assert "~ bar.conf  (content differs)" in text
    assert "-old_value=1" in text
    assert "+old_value=2" in text
