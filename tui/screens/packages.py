"""Package manager screen with hierarchy view and move/copy."""

from textual import work
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, RichLog

from tui.core.config import TTConfig
from tui.core.system import SystemInfo


class PackageScreen(Screen):
    """View and manage packages across the config hierarchy."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("m", "move_package", "Move"),
        ("c", "copy_package", "Copy"),
        ("tab", "switch_pane", "Switch Pane"),
    ]

    def __init__(self, tt_config: TTConfig, system: SystemInfo):
        super().__init__()
        self._tt_config = tt_config
        self._system = system

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="pkg-screen"):
            with Container(id="pkg-list-pane"):
                yield Label("Packages", classes="section-title")
                yield DataTable(id="pkg-table")
            with Container(id="pkg-info-pane"):
                yield Label("Details", classes="section-title")
                yield RichLog(id="pkg-info", wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#pkg-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("St", "Package", "Config")
        self._load_packages()

    def _load_packages(self) -> None:
        table = self.query_one("#pkg-table", DataTable)
        table.clear()
        host = self._system.hostname
        chain = self._tt_config.resolve_chain(host)
        installed = set()
        try:
            installed = set(self._system.list_installed_packages())
        except Exception:
            pass

        seen: set[str] = set()
        for cfg in chain:
            pkgs = self._tt_config.get_packages(cfg, self._system.installer)
            for pkg in sorted(pkgs):
                if pkg in seen:
                    continue
                seen.add(pkg)
                if installed:
                    status = "[green]OK[/]" if pkg in installed else "[red]!![/]"
                else:
                    status = "[dim]--[/]"
                if cfg == host:
                    tag = "[bold green]host[/]"
                elif cfg == "common":
                    tag = "[cyan]common[/]"
                else:
                    tag = f"[blue]{cfg}[/]"
                table.add_row(status, pkg, tag, key=f"{cfg}:{pkg}")

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None:
            return
        key = str(event.row_key.value)
        if ":" not in key:
            return
        config, pkg = key.split(":", 1)
        self._show_package_info(config, pkg)

    @work(thread=True)
    def _show_package_info(self, config: str, package: str) -> None:
        info_text = self._system.get_package_info(package)
        log = self.query_one("#pkg-info", RichLog)
        self.call_from_thread(log.clear)
        lines = [f"[bold]{package}[/]", f"Config: [cyan]{config}[/]", ""]
        chain = self._tt_config.resolve_chain(self._system.hostname)
        also_in = []
        for cfg in chain:
            if cfg == config:
                continue
            if package in self._tt_config.get_packages(cfg, self._system.installer):
                also_in.append(cfg)
        if also_in:
            lines.append(f"[yellow]Also in:[/] {', '.join(also_in)}")
            lines.append("")
        lines.append("[dim]--- Package Info ---[/]")
        lines.append(info_text)
        for line in lines:
            self.call_from_thread(log.write, line)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_move_package(self) -> None:
        table = self.query_one("#pkg-table", DataTable)
        row_idx = table.cursor_row
        if row_idx is None:
            return
        keys = list(table.rows.keys())
        if row_idx >= len(keys):
            return
        key = str(keys[row_idx].value)
        if ":" not in key:
            return
        source_config, pkg = key.split(":", 1)
        self._show_dest_picker(source_config, pkg, move=True)

    def action_copy_package(self) -> None:
        table = self.query_one("#pkg-table", DataTable)
        row_idx = table.cursor_row
        if row_idx is None:
            return
        keys = list(table.rows.keys())
        if row_idx >= len(keys):
            return
        key = str(keys[row_idx].value)
        if ":" not in key:
            return
        source_config, pkg = key.split(":", 1)
        self._show_dest_picker(source_config, pkg, move=False)

    def _show_dest_picker(self, source: str, package: str, move: bool) -> None:
        from tui.screens._dest_picker import DestPickerScreen
        self.app.push_screen(
            DestPickerScreen(self._tt_config, self._system, source, package, move),
            callback=self._on_dest_picked,
        )

    def _on_dest_picked(self, result: str | None) -> None:
        if result:
            self._load_packages()

    def action_switch_pane(self) -> None:
        if self.query_one("#pkg-table", DataTable).has_focus:
            self.query_one("#pkg-info", RichLog).focus()
        else:
            self.query_one("#pkg-table", DataTable).focus()
