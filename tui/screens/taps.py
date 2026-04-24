"""Tap manager screen — view, add, remove, and sync Homebrew taps."""

from rich.text import Text

from textual import work
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Footer, Header, Input, Label, OptionList, RichLog
from textual.widgets.option_list import Option

from tui.core.config import TTConfig
from tui.core.system import SystemInfo


class TapScreen(Screen):
    """Manage Homebrew taps across the config hierarchy."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("a", "add_tap", "Add Tap"),
        ("r", "remove_tap", "Remove"),
        ("m", "move_tap", "Move"),
        ("s", "sync_taps", "Sync All"),
        ("t", "tap_untapped", "Tap"),
        ("u", "untap", "Untap"),
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
                yield Label(
                    "Brew Taps  [dim]OK=tapped  !!=not tapped  ++=extra (not in config)[/]",
                    classes="section-title",
                )
                yield DataTable(id="tap-table")
            with Container(id="pkg-info-pane"):
                yield Label("Details", classes="section-title")
                yield RichLog(id="tap-info", wrap=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#tap-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("St", "Tap", "Config")
        self._load_taps()
        # Initial help
        log = self.query_one("#tap-info", RichLog)
        log.write(Text("Select a tap to see details.", style="dim"))
        log.write(Text(""))
        log.write(Text("Keybindings:", style="bold"))
        log.write(Text("  a  Add tap to a config", style="dim"))
        log.write(Text("  r  Remove tap from config", style="dim"))
        log.write(Text("  m  Move tap to another config", style="dim"))
        log.write(Text("  t  Tap (brew tap) a config tap", style="dim"))
        log.write(Text("  u  Untap (brew untap) from system", style="dim"))
        log.write(Text("  s  Sync all config taps to system", style="dim"))
        log.write(Text("  Esc  Back", style="dim"))

    def _load_taps(self) -> None:
        table = self.query_one("#tap-table", DataTable)
        table.clear()
        host = self._system.hostname
        chain = self._tt_config.resolve_chain(host)

        # Get system taps
        system_taps = set(self._system.list_current_taps())

        # Collect config taps with their source
        seen: set[str] = set()
        for cfg in chain:
            for tap in self._tt_config.get_taps(cfg):
                if tap in seen:
                    continue
                seen.add(tap)
                status = "OK" if tap in system_taps else "!!"
                st = Text(status)
                if status == "OK":
                    st.stylize("green")
                else:
                    st.stylize("bold red")

                cfg_text = Text(cfg)
                if cfg == host:
                    cfg_text.stylize("bold green")
                elif cfg == "common":
                    cfg_text.stylize("cyan")
                else:
                    cfg_text.stylize("blue")

                table.add_row(st, Text(tap), cfg_text, key=f"{cfg}:{tap}")

        # Extra taps (on system but not in any config)
        for tap in sorted(system_taps - seen):
            # Skip homebrew built-in taps
            if tap.startswith("homebrew/"):
                continue
            table.add_row(
                Text("++", style="yellow"),
                Text(tap),
                Text("system", style="yellow"),
                key=f"_extra_:{tap}",
            )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None:
            return
        key = str(event.row_key.value)
        if ":" not in key:
            return
        config, tap = key.split(":", 1)
        self._show_tap_info(config, tap)

    @work(thread=True)
    def _show_tap_info(self, config: str, tap: str) -> None:
        log = self.query_one("#tap-info", RichLog)
        self.app.call_from_thread(log.clear)

        self.app.call_from_thread(log.write, Text(tap, style="bold"))
        if config == "_extra_":
            self.app.call_from_thread(
                log.write, Text("Tapped on system but not in any config", style="yellow")
            )
        else:
            self.app.call_from_thread(
                log.write, Text(f"Config: {config}", style="cyan")
            )

        # Show which packages come from this tap
        self.app.call_from_thread(log.write, Text(""))
        self.app.call_from_thread(log.write, Text("Packages from this tap:", style="dim"))

        try:
            import subprocess
            result = subprocess.run(
                ["brew", "tap-info", "--json", tap],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                import json
                data = json.loads(result.stdout)
                for tap_info in data:
                    formula_names = tap_info.get("formula_names", [])
                    cask_names = tap_info.get("cask_tokens", [])
                    # Show which of these are installed
                    installed = set(self._system.list_installed_packages())
                    host = self._system.hostname
                    configured = set(
                        self._tt_config.get_effective_packages(host, self._system.installer)
                    )
                    for name in sorted(formula_names + cask_names):
                        short = name.rsplit("/", 1)[-1] if "/" in name else name
                        markers = []
                        if short in installed:
                            markers.append("installed")
                        if short in configured:
                            markers.append("in config")
                        if markers:
                            self.app.call_from_thread(
                                log.write,
                                Text(f"  {short}  ({', '.join(markers)})", style="green"),
                            )
        except Exception:
            self.app.call_from_thread(
                log.write, Text("  (could not fetch tap info)", style="dim")
            )

        self.app.call_from_thread(log.write, Text(""))
        self.app.call_from_thread(
            log.write,
            Text("a=add  r=remove  m=move  t=tap  u=untap  s=sync all", style="dim"),
        )

    def _get_selected_key(self) -> tuple[str, str] | None:
        table = self.query_one("#tap-table", DataTable)
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

    def action_go_back(self) -> None:
        self.dismiss(None)

    def action_add_tap(self) -> None:
        """Add a tap to a config. Pre-fills name when an extra (++) tap is selected."""
        prefill = ""
        result = self._get_selected_key()
        if result and result[0] == "_extra_":
            prefill = result[1]
        self.app.push_screen(
            AddTapScreen(self._tt_config, self._system, prefill=prefill),
            callback=self._on_tap_changed,
        )

    def _on_tap_changed(self, result: str | None) -> None:
        if result:
            self._load_taps()

    def action_remove_tap(self) -> None:
        """Remove the selected tap from its config."""
        result = self._get_selected_key()
        if not result:
            return
        config, tap = result
        if config == "_extra_":
            return
        self._tt_config._remove_tap(config, tap)
        log = self.query_one("#tap-info", RichLog)
        log.clear()
        log.write(Text(f"Removed {tap} from {config}", style="green"))
        self._load_taps()

    def action_move_tap(self) -> None:
        """Move tap to another config."""
        result = self._get_selected_key()
        if not result:
            return
        source, tap = result
        if source == "_extra_":
            return
        self.app.push_screen(
            MoveTapScreen(self._tt_config, self._system, source, tap),
            callback=self._on_tap_changed,
        )

    @work(thread=True)
    def action_tap_untapped(self) -> None:
        """Tap a configured but untapped tap on the system."""
        result = self._get_selected_key()
        if not result:
            return
        _, tap = result
        log = self.query_one("#tap-info", RichLog)
        self.app.call_from_thread(log.clear)
        self.app.call_from_thread(log.write, Text(f"Tapping {tap}...", style="yellow"))

        import subprocess
        try:
            proc = subprocess.run(
                ["brew", "tap", tap],
                capture_output=True, text=True, timeout=60,
            )
            output = proc.stdout + proc.stderr
            for line in output.splitlines():
                self.app.call_from_thread(log.write, Text(line))
            if proc.returncode == 0:
                self.app.call_from_thread(
                    log.write, Text(f"\nTapped {tap}!", style="bold green")
                )
            else:
                self.app.call_from_thread(
                    log.write, Text(f"\nFailed to tap {tap}", style="bold red")
                )
        except Exception as e:
            self.app.call_from_thread(log.write, Text(f"Error: {e}", style="red"))
        self.app.call_from_thread(self._load_taps)

    @work(thread=True)
    def action_untap(self) -> None:
        """Untap a tap from the system."""
        result = self._get_selected_key()
        if not result:
            return
        _, tap = result
        log = self.query_one("#tap-info", RichLog)
        self.app.call_from_thread(log.clear)
        self.app.call_from_thread(log.write, Text(f"Untapping {tap}...", style="yellow"))

        import subprocess
        try:
            proc = subprocess.run(
                ["brew", "untap", tap],
                capture_output=True, text=True, timeout=60,
            )
            output = proc.stdout + proc.stderr
            for line in output.splitlines():
                self.app.call_from_thread(log.write, Text(line))
            if proc.returncode == 0:
                self.app.call_from_thread(
                    log.write, Text(f"\nUntapped {tap}", style="bold green")
                )
            else:
                self.app.call_from_thread(
                    log.write, Text(f"\nFailed to untap {tap}", style="bold red")
                )
        except Exception as e:
            self.app.call_from_thread(log.write, Text(f"Error: {e}", style="red"))
        self.app.call_from_thread(self._load_taps)

    @work(thread=True)
    def action_sync_taps(self) -> None:
        """Sync all config taps to the system."""
        log = self.query_one("#tap-info", RichLog)
        self.app.call_from_thread(log.clear)
        self.app.call_from_thread(
            log.write, Text("Syncing all taps...", style="bold yellow")
        )

        host = self._system.hostname
        taps = self._tt_config.get_effective_taps(host)
        added = self._system.sync_taps(taps)
        if added:
            for tap in added:
                self.app.call_from_thread(
                    log.write, Text(f"  Tapped {tap}", style="green")
                )
            self.app.call_from_thread(
                log.write, Text(f"\n{len(added)} tap(s) added", style="bold green")
            )
        else:
            self.app.call_from_thread(
                log.write, Text("All taps already synced!", style="green")
            )
        self.app.call_from_thread(self._load_taps)

    def action_switch_pane(self) -> None:
        if self.query_one("#tap-table", DataTable).has_focus:
            self.query_one("#tap-info", RichLog).focus()
        else:
            self.query_one("#tap-table", DataTable).focus()


class AddTapScreen(ModalScreen[str | None]):
    """Modal to add a new tap."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    AddTapScreen {
        align: center middle;
    }
    #add-tap-dialog {
        width: 60;
        height: auto;
        max-height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #add-tap-dialog Input {
        margin: 1 0;
    }
    """

    def __init__(self, tt_config: TTConfig, system: SystemInfo, prefill: str = ""):
        super().__init__()
        self._tt_config = tt_config
        self._system = system
        self._prefill = prefill

    def compose(self) -> ComposeResult:
        with Container(id="add-tap-dialog"):
            if self._prefill:
                yield Label(f"[bold]Add [cyan]{self._prefill}[/cyan] to config[/]")
                yield Input(value=self._prefill, id="tap-name-input", disabled=True)
            else:
                yield Label("[bold]Add brew tap[/]")
                yield Input(
                    placeholder="user/repo (e.g. steipete/tap)",
                    id="tap-name-input",
                )
            yield Label("[dim]Select target config:[/]")
            options = []
            host = self._system.hostname
            for cfg in self._tt_config.list_configs():
                tag = ""
                if cfg == host:
                    tag = " [green][host][/]"
                elif cfg == "common":
                    tag = " [cyan][common][/]"
                options.append(Option(f"{cfg}{tag}", id=cfg))
            yield OptionList(*options, id="config-list")

    def on_mount(self) -> None:
        if self._prefill:
            self.query_one("#config-list", OptionList).focus()

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        tap = self.query_one("#tap-name-input", Input).value.strip()
        if not tap:
            return
        dest = str(event.option.id)
        self._tt_config.add_tap(dest, tap)
        self.dismiss(tap)

    def action_cancel(self) -> None:
        self.dismiss(None)


class MoveTapScreen(ModalScreen[str | None]):
    """Modal to move a tap to another config."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    MoveTapScreen {
        align: center middle;
    }
    #move-tap-dialog {
        width: 50;
        height: auto;
        max-height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, tt_config: TTConfig, system: SystemInfo, source: str, tap: str):
        super().__init__()
        self._tt_config = tt_config
        self._system = system
        self._source = source
        self._tap = tap

    def compose(self) -> ComposeResult:
        with Container(id="move-tap-dialog"):
            yield Label(f"[bold]Move[/] [cyan]{self._tap}[/] from [yellow]{self._source}[/] to:")
            options = []
            for cfg in self._tt_config.list_configs():
                if cfg == self._source:
                    continue
                tag = ""
                if cfg == self._system.hostname:
                    tag = " [green][host][/]"
                elif cfg == "common":
                    tag = " [cyan][common][/]"
                existing = self._tt_config.get_taps(cfg)
                if self._tap in existing:
                    tag += " [dim](has tap)[/]"
                options.append(Option(f"{cfg}{tag}", id=cfg))
            yield OptionList(*options)

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        dest = str(event.option.id)
        self._tt_config._remove_tap(self._source, self._tap)
        self._tt_config.add_tap(dest, self._tap)
        self.dismiss(dest)

    def action_cancel(self) -> None:
        self.dismiss(None)
