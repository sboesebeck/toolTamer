"""File manager screen with diff preview and hierarchy operations."""

import hashlib
from pathlib import Path

from rich.text import Text

from textual import work
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    RichLog,
)
from textual.widgets.option_list import Option

from tui.core.config import TTConfig
from tui.core.system import SystemInfo


class FileScreen(Screen):
    """View and manage tracked config files."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("a", "apply_to_system", "TT -> System"),
        ("u", "update_tooltamer", "System -> TT"),
        ("r", "remove_from_tt", "Remove"),
        ("m", "move_file", "Move"),
        ("o", "override_local", "Override Local"),
        ("n", "add_file", "Add File"),
        ("slash", "focus_search", "Search"),
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
                yield Label(
                    "Files  [dim]OK=synced  !!=changed  --=missing[/]",
                    classes="section-title",
                )
                yield Input(
                    placeholder="Filter files...",
                    id="file-filter",
                )
                yield DataTable(id="file-table")
            with Container(id="file-diff-pane"):
                yield Label("Details", classes="section-title")
                yield RichLog(id="file-diff", wrap=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#file-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("St", "Target", "Config")
        self._load_files()
        # Initial help
        log = self.query_one("#file-diff", RichLog)
        log.write(Text("Select a file to see diff.", style="dim"))
        log.write(Text(""))
        log.write(Text("Keybindings:", style="bold"))
        log.write(Text("  a  Apply TT -> System (overwrite local)", style="dim"))
        log.write(Text("  u  Update System -> TT (capture local)", style="dim"))
        log.write(Text("  r  Remove file from TT config", style="dim"))
        log.write(Text("  m  Move file to another config", style="dim"))
        log.write(Text("  o  Override locally (copy from parent)", style="dim"))
        log.write(Text("  n  Add new file to TT", style="dim"))
        log.write(Text("  /  Filter files", style="dim"))
        log.write(Text("  Esc  Back", style="dim"))

    def _load_files(self, filter_text: str = "") -> None:
        table = self.query_one("#file-table", DataTable)
        table.clear()
        host = self._system.hostname
        mappings = self._tt_config.get_effective_file_mappings(host)
        home = Path.home()
        for m in sorted(mappings, key=lambda x: x.target):
            if filter_text and filter_text.lower() not in m.target.lower():
                continue
            sys_file = home / m.target
            status = self._file_status(m.repo_path, sys_file)

            st = Text({"ok": "OK", "modified": "!!", "missing_system": "--", "missing_repo": "??"}.get(status, "??"))
            if status == "ok":
                st.stylize("green")
            elif status == "modified":
                st.stylize("bold yellow")
            else:
                st.stylize("red")

            cfg_text = Text(m.config)
            if m.config == host:
                cfg_text.stylize("bold green")
            elif m.config == "common":
                cfg_text.stylize("cyan")
            else:
                cfg_text.stylize("blue")

            table.add_row(
                st,
                Text(f"~/{m.target}"),
                cfg_text,
                key=f"{m.config}:{m.stored}:{m.target}",
            )

    def _refresh_files(self) -> None:
        current_filter = self.query_one("#file-filter", Input).value
        self._load_files(filter_text=current_filter)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "file-filter":
            self._load_files(filter_text=event.value)

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

    def _get_selected(self) -> tuple[str, str, str] | None:
        table = self.query_one("#file-table", DataTable)
        row_idx = table.cursor_row
        if row_idx is None:
            return None
        keys = list(table.rows.keys())
        if row_idx >= len(keys):
            return None
        key = str(keys[row_idx].value)
        parts = key.split(":", 2)
        if len(parts) != 3:
            return None
        return parts[0], parts[1], parts[2]

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
        self.app.call_from_thread(log.clear)
        repo_file = self._tt_config.configs_dir / config / "files" / stored
        sys_file = Path.home() / target
        host = self._system.hostname

        self.app.call_from_thread(log.write, Text(f"~/{target}", style="bold"))
        self.app.call_from_thread(log.write, Text(f"Config: {config}", style="cyan"))
        self.app.call_from_thread(log.write, Text(f"Stored as: {stored}", style="dim"))

        # Show if inherited from parent
        if config != host:
            self.app.call_from_thread(
                log.write,
                Text(f"Inherited from {config} (o=override locally)", style="yellow"),
            )

        self.app.call_from_thread(log.write, Text(""))

        if not repo_file.exists():
            self.app.call_from_thread(log.write, Text("Repo file missing", style="red"))
        elif not sys_file.exists():
            self.app.call_from_thread(log.write, Text("System file missing (a=apply from TT)", style="red"))
        elif repo_file.is_dir() or sys_file.is_dir():
            self.app.call_from_thread(log.write, Text("Directory target — no diff available", style="dim"))
        else:
            repo_hash = hashlib.sha1(repo_file.read_bytes()).hexdigest()
            sys_hash = hashlib.sha1(sys_file.read_bytes()).hexdigest()
            if repo_hash == sys_hash:
                self.app.call_from_thread(log.write, Text("Files are identical", style="green"))
            else:
                self.app.call_from_thread(log.write, Text("Files differ:", style="yellow"))
                self.app.call_from_thread(log.write, Text(""))
                try:
                    result = subprocess.run(
                        ["diff", "-u", str(repo_file), str(sys_file)],
                        capture_output=True, text=True, timeout=5,
                    )
                    for diff_line in result.stdout.splitlines()[:100]:
                        line = Text(diff_line)
                        if diff_line.startswith("+"):
                            line.stylize("green")
                        elif diff_line.startswith("-"):
                            line.stylize("red")
                        elif diff_line.startswith("@@"):
                            line.stylize("cyan")
                        self.app.call_from_thread(log.write, line)
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    self.app.call_from_thread(log.write, Text("diff command not available", style="dim"))

        self.app.call_from_thread(log.write, Text(""))
        self.app.call_from_thread(
            log.write,
            Text("a=apply TT->sys  u=sys->TT  r=remove  m=move  o=override", style="dim"),
        )

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_apply_to_system(self) -> None:
        """Copy repo file to system."""
        sel = self._get_selected()
        if not sel:
            return
        config, stored, target = sel
        repo_file = self._tt_config.configs_dir / config / "files" / stored
        sys_file = Path.home() / target
        if repo_file.exists() and not repo_file.is_dir():
            sys_file.parent.mkdir(parents=True, exist_ok=True)
            sys_file.write_bytes(repo_file.read_bytes())
            self._refresh_files()
            self._show_diff(config, stored, target)

    def action_update_tooltamer(self) -> None:
        """Copy system file to repo."""
        sel = self._get_selected()
        if not sel:
            return
        config, stored, target = sel
        repo_file = self._tt_config.configs_dir / config / "files" / stored
        sys_file = Path.home() / target
        if sys_file.exists() and not sys_file.is_dir():
            repo_file.parent.mkdir(parents=True, exist_ok=True)
            repo_file.write_bytes(sys_file.read_bytes())
            self._refresh_files()
            self._show_diff(config, stored, target)

    def action_remove_from_tt(self) -> None:
        """Remove file from TT config (stop managing it)."""
        sel = self._get_selected()
        if not sel:
            return
        config, stored, target = sel
        self._tt_config.remove_file_mapping(config, stored, target)
        log = self.query_one("#file-diff", RichLog)
        log.clear()
        log.write(Text(f"Removed ~/{target} from {config}", style="green"))
        log.write(Text("File remains on system, just no longer managed by TT.", style="dim"))
        self._refresh_files()

    def action_move_file(self) -> None:
        """Move file to another config."""
        sel = self._get_selected()
        if not sel:
            return
        config, stored, target = sel
        self.app.push_screen(
            MoveFileScreen(self._tt_config, self._system, config, stored, target),
            callback=self._on_file_changed,
        )

    def action_override_local(self) -> None:
        """Copy an inherited file to the host config for local modification."""
        sel = self._get_selected()
        if not sel:
            return
        config, stored, target = sel
        host = self._system.hostname
        if config == host:
            log = self.query_one("#file-diff", RichLog)
            log.clear()
            log.write(Text("Already in host config — nothing to override.", style="yellow"))
            return
        # Copy file from parent config to host config
        src_file = self._tt_config.configs_dir / config / "files" / stored
        if not src_file.exists():
            return
        dest_dir = self._tt_config.configs_dir / host / "files"
        dest_file = dest_dir / stored
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        dest_file.write_bytes(src_file.read_bytes())
        # Add mapping to host config
        self._tt_config.add_file_mapping(host, stored, target)
        log = self.query_one("#file-diff", RichLog)
        log.clear()
        log.write(Text(f"Copied ~/{target} to {host} config", style="green"))
        log.write(Text(f"Was inherited from {config}, now local.", style="dim"))
        log.write(Text("Edit the local copy, then u=update TT.", style="dim"))
        self._refresh_files()

    def action_add_file(self) -> None:
        """Add a new file to TT."""
        self.app.push_screen(
            AddFileScreen(self._tt_config, self._system),
            callback=self._on_file_changed,
        )

    def _on_file_changed(self, result: str | None) -> None:
        if result:
            self._refresh_files()

    def action_focus_search(self) -> None:
        self.query_one("#file-filter", Input).focus()

    def action_switch_pane(self) -> None:
        if self.query_one("#file-table", DataTable).has_focus:
            self.query_one("#file-diff", RichLog).focus()
        else:
            self.query_one("#file-table", DataTable).focus()


class MoveFileScreen(ModalScreen[str | None]):
    """Move a file to another config."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    MoveFileScreen {
        align: center middle;
    }
    #move-file-dialog {
        width: 50;
        height: auto;
        max-height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, tt_config: TTConfig, system: SystemInfo, source: str, stored: str, target: str):
        super().__init__()
        self._tt_config = tt_config
        self._system = system
        self._source = source
        self._stored = stored
        self._target = target

    def compose(self) -> ComposeResult:
        with Container(id="move-file-dialog"):
            yield Label(Text.assemble(
                ("Move ", "bold"),
                (f"~/{self._target}", "cyan"),
                (" from ", ""),
                (self._source, "yellow"),
                (" to:", ""),
            ))
            options = []
            host = self._system.hostname
            parents = self._tt_config.get_parents(host)
            for cfg in self._tt_config.list_configs():
                if cfg == self._source:
                    continue
                tag = ""
                if cfg == host:
                    tag = " [green][host][/]"
                elif cfg == "common":
                    tag = " [cyan][common][/]"
                elif cfg in parents:
                    tag = " [blue][parent][/]"
                options.append(Option(f"{cfg}{tag}", id=cfg))
            yield OptionList(*options)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        dest = str(event.option.id)
        # Copy file
        src_file = self._tt_config.configs_dir / self._source / "files" / self._stored
        dest_file = self._tt_config.configs_dir / dest / "files" / self._stored
        if src_file.exists():
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            dest_file.write_bytes(src_file.read_bytes())
        # Update mappings
        self._tt_config.remove_file_mapping(self._source, self._stored, self._target)
        self._tt_config.add_file_mapping(dest, self._stored, self._target)
        # Remove old file
        if src_file.exists():
            src_file.unlink()
        self.dismiss(dest)

    def action_cancel(self) -> None:
        self.dismiss(None)


class AddFileScreen(ModalScreen[str | None]):
    """Add a system file to TT management."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    AddFileScreen {
        align: center middle;
    }
    #add-file-dialog {
        width: 60;
        height: auto;
        max-height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #add-file-dialog Input {
        margin: 1 0;
    }
    """

    def __init__(self, tt_config: TTConfig, system: SystemInfo):
        super().__init__()
        self._tt_config = tt_config
        self._system = system

    def compose(self) -> ComposeResult:
        with Container(id="add-file-dialog"):
            yield Label(Text("Add file to ToolTamer", style="bold"))
            yield Label(Text("Path relative to ~ (e.g. .config/foo/bar.toml):", style="dim"))
            yield Input(placeholder="~/.config/...", id="file-path-input")
            yield Label(Text("Select target config:", style="dim"))
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

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        rel_path = self.query_one("#file-path-input", Input).value.strip()
        if not rel_path:
            return
        # Remove leading ~/ if present
        rel_path = rel_path.removeprefix("~/").removeprefix("~")
        sys_file = Path.home() / rel_path
        if not sys_file.exists():
            return

        dest = str(event.option.id)
        # Sanitize stored name (replace / with _/)
        stored = rel_path.replace("/", "_/") if "/" in rel_path else rel_path
        dest_file = self._tt_config.configs_dir / dest / "files" / stored
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        if sys_file.is_file():
            dest_file.write_bytes(sys_file.read_bytes())
        self._tt_config.add_file_mapping(dest, stored, rel_path)
        self.dismiss(rel_path)

    def action_cancel(self) -> None:
        self.dismiss(None)
