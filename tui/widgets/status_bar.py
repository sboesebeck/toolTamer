"""Status summary widget for the dashboard."""

import hashlib
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Label

from tui.core.config import TTConfig
from tui.core.system import SystemInfo


class StatusBar(Widget):
    """Shows host, OS, installer, and live change counts."""

    def __init__(
        self,
        tt_config: TTConfig,
        system: SystemInfo,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._tt_config = tt_config
        self._system = system

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("Host  ", classes="label-key")
            yield Label(self._system.hostname, classes="label-value", id="host-value")
        with Horizontal():
            yield Label("OS    ", classes="label-key")
            yield Label(
                f"{self._system.os_type} ({self._system.installer})",
                classes="label-value",
            )
        with Horizontal():
            yield Label("Configs ", classes="label-key")
            chain = self._tt_config.resolve_chain(self._system.hostname)
            yield Label(
                " → ".join(chain),
                classes="label-value",
            )
        with Horizontal():
            yield Label("Pkgs  ", classes="label-key")
            yield Label("[dim]scanning...[/]", classes="label-value", id="pkg-count")
        with Horizontal():
            yield Label("Files ", classes="label-key")
            yield Label("[dim]scanning...[/]", classes="label-value", id="file-count")

    def on_mount(self) -> None:
        self._scan_status()

    @work(thread=True)
    def _scan_status(self) -> None:
        host = self._system.hostname
        installer = self._system.installer

        # Package counts
        effective = self._tt_config.get_effective_packages(host, installer)
        total_pkgs = len(effective)
        try:
            installed = set(self._system.list_installed_packages())
            missing = sum(1 for p in effective if p not in installed)
            excess = sum(1 for p in installed if p not in set(effective))
            pkg_text = f"{total_pkgs} managed"
            if missing:
                pkg_text += f", [red]{missing} missing[/]"
            if excess:
                pkg_text += f", [yellow]{excess} extra[/]"
            if not missing and not excess:
                pkg_text += " [green]— all synced[/]"
        except Exception:
            pkg_text = f"{total_pkgs} managed"

        self.app.call_from_thread(
            self.query_one("#pkg-count", Label).update, pkg_text
        )

        # File counts
        mappings = self._tt_config.get_effective_file_mappings(host)
        total_files = len(mappings)
        modified = 0
        missing_files = 0
        home = Path.home()
        for m in mappings:
            sys_file = home / m.target
            if not m.repo_path.exists() or not sys_file.exists():
                missing_files += 1
            elif sys_file.is_dir() or m.repo_path.is_dir():
                continue
            else:
                try:
                    if hashlib.sha1(m.repo_path.read_bytes()).hexdigest() != hashlib.sha1(sys_file.read_bytes()).hexdigest():
                        modified += 1
                except (OSError, PermissionError):
                    continue

        file_text = f"{total_files} managed"
        if modified:
            file_text += f", [yellow]{modified} changed[/]"
        if missing_files:
            file_text += f", [red]{missing_files} missing[/]"
        if not modified and not missing_files:
            file_text += " [green]— all synced[/]"

        self.app.call_from_thread(
            self.query_one("#file-count", Label).update, file_text
        )
