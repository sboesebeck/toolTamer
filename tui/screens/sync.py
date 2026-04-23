"""Sync screen with live subprocess output."""

from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, RichLog, Static

from tui.core.config import TTConfig
from tui.core.system import SystemInfo


class SyncScreen(Screen):
    """Run sync operations with live output."""

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, tt_config: TTConfig, system: SystemInfo, mode: str = "full"):
        super().__init__()
        self._tt_config = tt_config
        self._system = system
        self._mode = mode

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="sync-screen"):
            title_map = {
                "full": "Full System Sync",
                "files": "Files Only Sync",
                "snapshot": "Snapshot to ToolTamer",
            }
            yield Label(title_map.get(self._mode, "Sync"), classes="section-title")
            yield RichLog(id="sync-log", wrap=True, highlight=True)
            with Container(id="sync-progress"):
                yield Static("[dim]Running...[/]", id="sync-status")
        yield Footer()

    def on_mount(self) -> None:
        self._run_sync()

    @work(thread=True)
    def _run_sync(self) -> None:
        import os
        import subprocess

        log = self.query_one("#sync-log", RichLog)
        status = self.query_one("#sync-status", Static)

        # Find tt script
        tt_script = None
        for candidate in [
            Path.home() / "toolTamer" / "bin" / "tt",
            Path("/usr/local/bin/tt"),
        ]:
            if candidate.exists():
                tt_script = candidate
                break

        flag_map = {
            "full": "--syncSys",
            "files": "--syncFilesOnly",
            "snapshot": "--updateToolTamerFiles",
        }
        flag = flag_map.get(self._mode, "--syncSys")

        if tt_script is None:
            self.app.call_from_thread(
                log.write,
                "[red]Error:[/] tt script not found. Make sure ~/toolTamer/bin/tt exists.",
            )
            self.app.call_from_thread(status.update, "[red]Error[/] — press ESC to return")
            return

        self.app.call_from_thread(log.write, f"[bold]Running:[/] tt {flag}\n")

        try:
            proc = subprocess.Popen(
                ["bash", str(tt_script), flag],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env={**os.environ, "TERM": "dumb"},
            )
            for line in iter(proc.stdout.readline, ""):
                if not line:
                    break
                self.app.call_from_thread(log.write, line.rstrip())

            proc.wait()
            if proc.returncode == 0:
                self.app.call_from_thread(status.update, "[green]Complete[/] — press ESC to return")
            else:
                self.app.call_from_thread(
                    status.update,
                    f"[red]Failed[/] (exit {proc.returncode}) — press ESC to return",
                )
        except FileNotFoundError:
            self.app.call_from_thread(
                log.write,
                "[red]Error:[/] bash not found.",
            )
            self.app.call_from_thread(status.update, "[red]Error[/] — press ESC to return")

    def action_go_back(self) -> None:
        self.app.pop_screen()
