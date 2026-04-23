"""File manager screen with diff preview."""

import hashlib
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, RichLog

from tui.core.config import FileMapping, TTConfig
from tui.core.system import SystemInfo


class FileScreen(Screen):
    """View and manage tracked config files."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("a", "apply_to_system", "Apply to System"),
        ("u", "update_tooltamer", "Update TT"),
        ("tab", "switch_pane", "Switch Pane"),
    ]

    def __init__(self, tt_config: TTConfig, system: SystemInfo):
        super().__init__()
        self._tt_config = tt_config
        self._system = system

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="file-screen"):
            with Container(id="file-list-pane"):
                yield Label("Managed Files", classes="section-title")
                yield DataTable(id="file-table")
            with Container(id="file-diff-pane"):
                yield Label("Diff Preview", classes="section-title")
                yield RichLog(id="file-diff", wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#file-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("St", "Target", "Config")
        self._load_files()

    def _load_files(self) -> None:
        table = self.query_one("#file-table", DataTable)
        table.clear()
        host = self._system.hostname
        mappings = self._tt_config.get_effective_file_mappings(host)
        home = Path.home()
        for m in sorted(mappings, key=lambda x: x.target):
            sys_file = home / m.target
            status = self._file_status(m.repo_path, sys_file)
            status_display = {
                "ok": "[green]OK[/]",
                "modified": "[yellow]!![/]",
                "missing_system": "[red]--[/]",
                "missing_repo": "[red]??[/]",
            }.get(status, "[dim]??[/]")
            table.add_row(
                status_display,
                f"~/{m.target}",
                f"[cyan]{m.config}[/]",
                key=f"{m.config}:{m.stored}:{m.target}",
            )

    def _file_status(self, repo: Path, system: Path) -> str:
        if not repo.exists():
            return "missing_repo"
        if not system.exists():
            return "missing_system"
        if repo.is_dir() or system.is_dir():
            return "ok"
        try:
            repo_hash = hashlib.sha1(repo.read_bytes()).hexdigest()
            sys_hash = hashlib.sha1(system.read_bytes()).hexdigest()
            return "ok" if repo_hash == sys_hash else "modified"
        except (OSError, PermissionError):
            return "ok"

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None:
            return
        key = str(event.row_key.value)
        parts = key.split(":", 2)
        if len(parts) != 3:
            return
        config, stored, target = parts
        self._show_diff(config, stored, target)

    @work(thread=True)
    def _show_diff(self, config: str, stored: str, target: str) -> None:
        import subprocess
        log = self.query_one("#file-diff", RichLog)
        self.call_from_thread(log.clear)
        repo_file = self._tt_config.configs_dir / config / "files" / stored
        sys_file = Path.home() / target
        lines = [f"[bold]~/{target}[/]", f"Config: [cyan]{config}[/]", f"Repo:   {repo_file}", ""]
        if not repo_file.exists():
            lines.append("[red]Repo file missing[/]")
        elif not sys_file.exists():
            lines.append("[red]System file missing[/]")
        else:
            repo_hash = hashlib.sha1(repo_file.read_bytes()).hexdigest()
            sys_hash = hashlib.sha1(sys_file.read_bytes()).hexdigest()
            if repo_hash == sys_hash:
                lines.append("[green]Files are identical[/]")
            else:
                lines.append("[yellow]Files differ:[/]")
                lines.append("")
                try:
                    result = subprocess.run(
                        ["diff", "-u", str(repo_file), str(sys_file)],
                        capture_output=True, text=True, timeout=5,
                    )
                    for diff_line in result.stdout.splitlines()[:100]:
                        if diff_line.startswith("+"):
                            lines.append(f"[green]{diff_line}[/]")
                        elif diff_line.startswith("-"):
                            lines.append(f"[red]{diff_line}[/]")
                        elif diff_line.startswith("@@"):
                            lines.append(f"[cyan]{diff_line}[/]")
                        else:
                            lines.append(diff_line)
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    lines.append("[dim]diff command not available[/]")
        for line in lines:
            self.call_from_thread(log.write, line)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_apply_to_system(self) -> None:
        table = self.query_one("#file-table", DataTable)
        row_idx = table.cursor_row
        if row_idx is None:
            return
        keys = list(table.rows.keys())
        if row_idx >= len(keys):
            return
        key = str(keys[row_idx].value)
        parts = key.split(":", 2)
        if len(parts) != 3:
            return
        config, stored, target = parts
        repo_file = self._tt_config.configs_dir / config / "files" / stored
        sys_file = Path.home() / target
        if repo_file.exists():
            sys_file.parent.mkdir(parents=True, exist_ok=True)
            sys_file.write_bytes(repo_file.read_bytes())
            self._load_files()
            self._show_diff(config, stored, target)

    def action_update_tooltamer(self) -> None:
        table = self.query_one("#file-table", DataTable)
        row_idx = table.cursor_row
        if row_idx is None:
            return
        keys = list(table.rows.keys())
        if row_idx >= len(keys):
            return
        key = str(keys[row_idx].value)
        parts = key.split(":", 2)
        if len(parts) != 3:
            return
        config, stored, target = parts
        repo_file = self._tt_config.configs_dir / config / "files" / stored
        sys_file = Path.home() / target
        if sys_file.exists():
            repo_file.parent.mkdir(parents=True, exist_ok=True)
            repo_file.write_bytes(sys_file.read_bytes())
            self._load_files()
            self._show_diff(config, stored, target)

    def action_switch_pane(self) -> None:
        if self.query_one("#file-table", DataTable).has_focus:
            self.query_one("#file-diff", RichLog).focus()
        else:
            self.query_one("#file-table", DataTable).focus()
