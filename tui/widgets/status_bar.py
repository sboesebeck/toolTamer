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
    """Shows host, OS, installer, and live change details."""

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
            yield Label("Host    ", classes="label-key")
            yield Label(self._system.hostname, classes="label-value", id="host-value")
        with Horizontal():
            yield Label("OS      ", classes="label-key")
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
            yield Label("Pkgs    ", classes="label-key")
            yield Label("[dim]scanning...[/]", classes="label-value", id="pkg-count")
        yield Label("", id="pkg-details")
        with Horizontal():
            yield Label("Files   ", classes="label-key")
            yield Label("[dim]scanning...[/]", classes="label-value", id="file-count")
        yield Label("", id="file-details")

    def on_mount(self) -> None:
        self._scan_status()

    @work(thread=True)
    def _scan_status(self) -> None:
        host = self._system.hostname
        installer = self._system.installer

        # Package scan
        effective = self._tt_config.get_effective_packages(host, installer)
        effective_set = set(effective)
        total_pkgs = len(effective)
        try:
            installed = set(self._system.list_installed_packages())
            missing_pkgs = sorted(p for p in effective if p not in installed)
            excess_pkgs = sorted(p for p in installed if p not in effective_set)

            pkg_text = f"{total_pkgs} managed"
            if missing_pkgs:
                pkg_text += f", [red]{len(missing_pkgs)} missing[/]"
            if excess_pkgs:
                pkg_text += f", [yellow]{len(excess_pkgs)} extra[/]"
            if not missing_pkgs and not excess_pkgs:
                pkg_text += " [green]— all synced[/]"

            # Build detail lines
            pkg_detail_parts = []
            if missing_pkgs:
                names = ", ".join(missing_pkgs[:10])
                if len(missing_pkgs) > 10:
                    names += f" +{len(missing_pkgs) - 10} more"
                pkg_detail_parts.append(f"[red]Missing:[/] {names}")
            if excess_pkgs:
                names = ", ".join(excess_pkgs[:10])
                if len(excess_pkgs) > 10:
                    names += f" +{len(excess_pkgs) - 10} more"
                pkg_detail_parts.append(f"[yellow]Extra:[/] {names}")
            pkg_details = " | ".join(pkg_detail_parts) if pkg_detail_parts else ""

        except Exception:
            pkg_text = f"{total_pkgs} managed"
            pkg_details = ""

        self.app.call_from_thread(
            self.query_one("#pkg-count", Label).update, pkg_text
        )
        self.app.call_from_thread(
            self.query_one("#pkg-details", Label).update, pkg_details
        )

        # File scan
        mappings = self._tt_config.get_effective_file_mappings(host)
        total_files = len(mappings)
        modified_files: list[str] = []
        missing_file_names: list[str] = []
        home = Path.home()
        for m in mappings:
            sys_file = home / m.target
            if not m.repo_path.exists() or not sys_file.exists():
                missing_file_names.append(m.target)
            elif sys_file.is_dir() or m.repo_path.is_dir():
                continue
            else:
                try:
                    if hashlib.sha1(m.repo_path.read_bytes()).hexdigest() != hashlib.sha1(sys_file.read_bytes()).hexdigest():
                        modified_files.append(m.target)
                except (OSError, PermissionError):
                    continue

        file_text = f"{total_files} managed"
        if modified_files:
            file_text += f", [yellow]{len(modified_files)} changed[/]"
        if missing_file_names:
            file_text += f", [red]{len(missing_file_names)} missing[/]"
        if not modified_files and not missing_file_names:
            file_text += " [green]— all synced[/]"

        file_detail_parts = []
        if modified_files:
            names = ", ".join(modified_files[:5])
            if len(modified_files) > 5:
                names += f" +{len(modified_files) - 5} more"
            file_detail_parts.append(f"[yellow]Changed:[/] {names}")
        if missing_file_names:
            names = ", ".join(missing_file_names[:5])
            if len(missing_file_names) > 5:
                names += f" +{len(missing_file_names) - 5} more"
            file_detail_parts.append(f"[red]Missing:[/] {names}")
        file_details = " | ".join(file_detail_parts) if file_detail_parts else ""

        self.app.call_from_thread(
            self.query_one("#file-count", Label).update, file_text
        )
        self.app.call_from_thread(
            self.query_one("#file-details", Label).update, file_details
        )
