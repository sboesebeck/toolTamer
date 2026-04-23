"""Package manager screen with hierarchy view and move/copy."""

from rich.text import Text

from textual import work
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Label, RichLog

from tui.core.config import TTConfig
from tui.core.system import SystemInfo


class PackageScreen(Screen):
    """View and manage packages across the config hierarchy."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("m", "move_package", "Move"),
        ("c", "copy_package", "Copy"),
        ("i", "install_package", "Install"),
        ("x", "uninstall_package", "Uninstall"),
        ("r", "remove_from_config", "Remove from Config"),
        ("a", "add_to_config", "Add to Config"),
        ("slash", "focus_search", "Search"),
        ("tab", "switch_pane", "Switch Pane"),
    ]

    def __init__(self, tt_config: TTConfig, system: SystemInfo):
        super().__init__()
        self._tt_config = tt_config
        self._system = system
        self._all_rows: list[tuple[str, str, str, str]] = []  # status, pkg, tag, key

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="pkg-screen"):
            with Container(id="pkg-list-pane"):
                yield Label(
                    "Packages  [dim]OK=installed  !!=missing  ++=extra  --=unknown[/]",
                    classes="section-title",
                )
                yield Input(
                    placeholder="Filter... (text, or: !! missing, OK installed, ++ extra)",
                    id="pkg-filter",
                )
                yield DataTable(id="pkg-table")
            with Container(id="pkg-info-pane"):
                yield Label("Details", classes="section-title")
                yield RichLog(id="pkg-info", wrap=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#pkg-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("St", "Package", "Config")
        self._load_packages()
        # Show initial help in info pane
        log = self.query_one("#pkg-info", RichLog)
        log.write(Text("Select a package to see details.", style="dim"))
        log.write(Text(""))
        log.write(Text("Keybindings:", style="bold"))
        log.write(Text("  i  Install missing package", style="dim"))
        log.write(Text("  x  Uninstall package from system", style="dim"))
        log.write(Text("  m  Move package to another config", style="dim"))
        log.write(Text("  c  Copy package to another config", style="dim"))
        log.write(Text("  r  Remove package from config", style="dim"))
        log.write(Text("  a  Add new package to config", style="dim"))
        log.write(Text("  /  Filter packages", style="dim"))
        log.write(Text("  Esc  Back to dashboard", style="dim"))

    def _refresh_packages(self) -> None:
        """Reload packages preserving the current filter."""
        current_filter = self.query_one("#pkg-filter", Input).value
        self._load_packages(filter_text=current_filter)

    def _load_packages(self, filter_text: str = "") -> None:
        table = self.query_one("#pkg-table", DataTable)
        table.clear()
        host = self._system.hostname
        chain = self._tt_config.resolve_chain(host)
        installed = set()
        try:
            installed = set(self._system.list_installed_packages())
        except Exception:
            pass

        effective_set = set()
        self._all_rows = []
        seen: set[str] = set()
        for cfg in chain:
            pkgs = self._tt_config.get_packages(cfg, self._system.installer)
            for pkg in sorted(pkgs):
                if pkg in seen:
                    continue
                seen.add(pkg)
                effective_set.add(pkg)
                if installed:
                    status = "OK" if pkg in installed else "!!"
                else:
                    status = "--"
                if cfg == host:
                    tag = "host"
                elif cfg == "common":
                    tag = "common"
                else:
                    tag = cfg
                self._all_rows.append((status, pkg, tag, f"{cfg}:{pkg}"))

        # Add extra packages (installed but not in any config)
        if installed:
            extras = sorted(installed - effective_set)
            for pkg in extras:
                self._all_rows.append(("++", pkg, "system", f"_extra_:{pkg}"))

        # Determine filter mode
        ft = filter_text.strip().lower()
        status_filter = None
        name_filter = ""
        if ft == "!!":
            status_filter = "!!"
        elif ft == "ok":
            status_filter = "OK"
        elif ft == "++":
            status_filter = "++"
        elif ft == "--":
            status_filter = "--"
        elif ft:
            name_filter = ft

        for status, pkg, tag, key in self._all_rows:
            if status_filter and status != status_filter:
                continue
            if name_filter and name_filter not in pkg.lower():
                continue

            st = Text(status)
            if status == "OK":
                st.stylize("green")
            elif status == "!!":
                st.stylize("bold red")
            elif status == "++":
                st.stylize("yellow")
            else:
                st.stylize("dim")

            cfg_text = Text(tag)
            if tag == "host":
                cfg_text.stylize("bold green")
            elif tag == "common":
                cfg_text.stylize("cyan")
            elif tag == "system":
                cfg_text.stylize("yellow")
            else:
                cfg_text.stylize("blue")

            table.add_row(st, Text(pkg), cfg_text, key=key)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "pkg-filter":
            self._load_packages(filter_text=event.value)

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
        self.app.call_from_thread(log.clear)

        self.app.call_from_thread(log.write, Text(package, style="bold"))
        self.app.call_from_thread(log.write, Text(f"Config: {config}", style="cyan"))
        self.app.call_from_thread(log.write, Text(""))

        # Show where else this package appears
        chain = self._tt_config.resolve_chain(self._system.hostname)
        also_in = []
        for cfg in chain:
            if cfg == config:
                continue
            if package in self._tt_config.get_packages(cfg, self._system.installer):
                also_in.append(cfg)
        if also_in:
            self.app.call_from_thread(
                log.write, Text(f"Also in: {', '.join(also_in)}", style="yellow")
            )
            self.app.call_from_thread(log.write, Text(""))

        self.app.call_from_thread(
            log.write, Text("--- Package Info ---", style="dim")
        )
        for info_line in info_text.splitlines():
            self.app.call_from_thread(log.write, Text(info_line))

        # Show status-specific hints
        installed = set()
        try:
            installed = set(self._system.list_installed_packages())
        except Exception:
            pass
        self.app.call_from_thread(log.write, Text(""))
        if package not in installed:
            self.app.call_from_thread(
                log.write, Text("i=install  r=remove from config  m=move  c=copy", style="dim")
            )
        else:
            self.app.call_from_thread(
                log.write, Text("x=uninstall  r=remove from config  m=move  c=copy", style="dim")
            )

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def _get_selected_key(self) -> tuple[str, str] | None:
        table = self.query_one("#pkg-table", DataTable)
        row_idx = table.cursor_row
        if row_idx is None:
            return None
        keys = list(table.rows.keys())
        if row_idx >= len(keys):
            return None
        key = str(keys[row_idx].value)
        if ":" not in key:
            return None
        return key.split(":", 1)

    def action_move_package(self) -> None:
        result = self._get_selected_key()
        if result:
            self._show_dest_picker(result[0], result[1], move=True)

    def action_copy_package(self) -> None:
        result = self._get_selected_key()
        if result:
            self._show_dest_picker(result[0], result[1], move=False)

    def _show_dest_picker(self, source: str, package: str, move: bool) -> None:
        from tui.screens._dest_picker import DestPickerScreen
        self.app.push_screen(
            DestPickerScreen(self._tt_config, self._system, source, package, move),
            callback=self._on_dest_picked,
        )

    def _on_dest_picked(self, result: str | None) -> None:
        if result:
            self._refresh_packages()

    def action_install_package(self) -> None:
        """Install the selected missing package."""
        result = self._get_selected_key()
        if not result:
            return
        _, pkg = result
        self._run_pkg_action(pkg, "install")

    def action_uninstall_package(self) -> None:
        """Uninstall the selected package from the system."""
        result = self._get_selected_key()
        if not result:
            return
        _, pkg = result
        self._run_pkg_action(pkg, "uninstall")

    def action_remove_from_config(self) -> None:
        """Remove the selected package from its config file."""
        result = self._get_selected_key()
        if not result:
            return
        config, pkg = result
        self._tt_config._remove_package(config, pkg, self._system.installer)
        log = self.query_one("#pkg-info", RichLog)
        log.clear()
        log.write(Text(f"Removed {pkg} from {config}", style="green"))
        self._refresh_packages()

    def action_add_to_config(self) -> None:
        """Add a new package to a config (prompts for name)."""
        from tui.screens._add_package import AddPackageScreen
        self.app.push_screen(
            AddPackageScreen(self._tt_config, self._system),
            callback=self._on_package_added,
        )

    def _on_package_added(self, result: str | None) -> None:
        if result:
            self._refresh_packages()

    @work(thread=True)
    def _run_pkg_action(self, package: str, action: str) -> None:
        log = self.query_one("#pkg-info", RichLog)
        self.app.call_from_thread(log.clear)

        if action == "install":
            # Sync taps first (brew only)
            taps = self._tt_config.get_effective_taps(self._system.hostname)
            if taps:
                self.app.call_from_thread(
                    log.write, Text("Syncing brew taps...", style="dim")
                )
                added = self._system.sync_taps(taps)
                for tap in added:
                    self.app.call_from_thread(
                        log.write, Text(f"  Tapped {tap}", style="green")
                    )
            self.app.call_from_thread(
                log.write, Text(f"Installing {package}...", style="bold yellow")
            )
            success, output = self._system.install_package(package)
        else:
            self.app.call_from_thread(
                log.write, Text(f"Uninstalling {package}...", style="bold yellow")
            )
            success, output = self._system.uninstall_package(package)

        for line in output.splitlines():
            self.app.call_from_thread(log.write, Text(line))

        if success:
            self.app.call_from_thread(
                log.write, Text(f"\n{action.title()} successful!", style="bold green")
            )
        else:
            self.app.call_from_thread(
                log.write, Text(f"\n{action.title()} failed.", style="bold red")
            )
        # Refresh the table on the main thread
        self.app.call_from_thread(self._refresh_packages)

    def action_focus_search(self) -> None:
        self.query_one("#pkg-filter", Input).focus()

    def action_switch_pane(self) -> None:
        if self.query_one("#pkg-table", DataTable).has_focus:
            self.query_one("#pkg-info", RichLog).focus()
        else:
            self.query_one("#pkg-table", DataTable).focus()
