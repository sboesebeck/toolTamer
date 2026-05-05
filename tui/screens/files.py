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


def _dir_deletions(source: Path, dest: Path) -> list[str]:
    """Return relative paths that exist under dest but not source — i.e., the
    files that would be removed by replacing dest with a fresh copy of source."""
    if not (dest.exists() and dest.is_dir() and source.exists() and source.is_dir()):
        return []
    src_rel: set[str] = set()
    for p in source.rglob("*"):
        if p.is_file() or p.is_symlink():
            src_rel.add(str(p.relative_to(source)))
    deletions: list[str] = []
    for p in dest.rglob("*"):
        if p.is_file() or p.is_symlink():
            rel = str(p.relative_to(dest))
            if rel not in src_rel:
                deletions.append(rel)
    return sorted(deletions)


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
                    "Files  [dim]OK=synced  !!=changed  --=missing  <<=shadowed  ===dup-in-config[/]",
                    classes="section-title",
                )
                yield Input(
                    placeholder="Filter (path, config, or status: OK !! -- ?? << ==)",
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
        log.write(Text("  n  Add new file or directory to TT", style="dim"))
        log.write(Text("  /  Filter files", style="dim"))
        log.write(Text("  Esc  Back", style="dim"))

    def _load_files(self, filter_text: str = "") -> None:
        table = self.query_one("#file-table", DataTable)
        table.clear()
        host = self._system.hostname
        mappings = self._tt_config.get_effective_file_mappings(host)
        home = Path.home()
        filt = filter_text.lower().strip()
        # Sort: by effective target, effective entries before shadowed ones
        for m in sorted(mappings, key=lambda x: (x.effective_target, not x.is_effective)):
            eff_target = m.effective_target
            sys_file = home / eff_target
            status = self._file_status(m.repo_path, sys_file)

            self_shadow = (not m.is_effective) and m.shadowed_by == m.config
            if not m.is_effective:
                status_token = "==" if self_shadow else "<<"
            else:
                status_token = {
                    "ok": "OK",
                    "modified": "!!",
                    "missing_system": "--",
                    "missing_repo": "??",
                }.get(status, "??")

            # Filter matches status code, path, or config name
            if filt:
                searchable = f"{status_token} ~/{eff_target} {m.config}".lower()
                if filt not in searchable:
                    continue

            st = Text(status_token)
            if self_shadow:
                st.stylize("dim yellow")
            elif not m.is_effective:
                st.stylize("dim magenta")
            elif status == "ok":
                st.stylize("green")
            elif status == "modified":
                st.stylize("bold yellow")
            else:
                st.stylize("red")

            target_text = Text(f"~/{eff_target}")
            cfg_text = Text(m.config)
            if not m.is_effective:
                target_text.stylize("dim")
                cfg_text.stylize("dim strike")
            elif m.config == host:
                cfg_text.stylize("bold green")
            elif m.config == "common":
                cfg_text.stylize("cyan")
            else:
                cfg_text.stylize("blue")

            table.add_row(
                st,
                target_text,
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
        from tui.core.config import _resolve_effective_target
        eff_target = _resolve_effective_target(stored, target)
        sys_file = Path.home() / eff_target
        host = self._system.hostname

        self.app.call_from_thread(log.write, Text(f"~/{eff_target}", style="bold"))
        self.app.call_from_thread(log.write, Text(f"Config: {config}", style="cyan"))
        self.app.call_from_thread(log.write, Text(f"Stored as: {stored}", style="dim"))

        # Identify shadowing relationships for this target
        all_for_target = [
            m for m in self._tt_config.get_effective_file_mappings(host)
            if m.effective_target == eff_target
        ]
        winner = next((m for m in all_for_target if m.is_effective), None)
        is_shadowed = (
            winner is not None
            and not (winner.config == config and winner.stored == stored)
        )
        is_self_shadow = is_shadowed and winner is not None and winner.config == config

        if is_self_shadow:
            self.app.call_from_thread(
                log.write,
                Text(
                    f"Duplicate inside '{config}' — same effective target also listed as '{winner.stored}'.",
                    style="bold yellow",
                ),
            )
            self.app.call_from_thread(
                log.write,
                Text("(r=remove this stale entry; the other line in this config wins)", style="dim"),
            )
        elif is_shadowed:
            self.app.call_from_thread(
                log.write,
                Text(
                    f"Shadowed by '{winner.config}' — this mapping is inactive on this host.",
                    style="bold magenta",
                ),
            )
            self.app.call_from_thread(
                log.write,
                Text("(r=remove this duplicate; system file follows the winning config)", style="dim"),
            )
        elif config != host and winner is not None:
            shadows = [m.config for m in all_for_target if m.config != config]
            if shadows:
                self.app.call_from_thread(
                    log.write,
                    Text(
                        f"Effective here. Also mapped (and shadowed) in: {', '.join(shadows)}",
                        style="yellow",
                    ),
                )
            self.app.call_from_thread(
                log.write,
                Text(f"Inherited from {config} (o=override locally)", style="yellow"),
            )
        elif config == host and len(all_for_target) > 1:
            shadows = [m.config for m in all_for_target if m.config != config]
            self.app.call_from_thread(
                log.write,
                Text(
                    f"Also mapped (and shadowed) in: {', '.join(shadows)}",
                    style="yellow",
                ),
            )

        self.app.call_from_thread(log.write, Text(""))

        if is_shadowed:
            # Skip the diff for shadowed entries — the on-disk file reflects
            # the winning config's content, which would be misleading here.
            self.app.call_from_thread(
                log.write,
                Text("Diff hidden: system file reflects the winning config.", style="dim"),
            )
            self.app.call_from_thread(log.write, Text(""))
            self.app.call_from_thread(
                log.write,
                Text("r=remove this duplicate  m=move", style="dim"),
            )
            return

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
        self.dismiss(None)

    def action_apply_to_system(self) -> None:
        """Copy repo file/dir to system. For directories with files that would
        be deleted on the system side, ask for confirmation first."""
        sel = self._get_selected()
        if not sel:
            return
        config, stored, target = sel
        from tui.core.config import _resolve_effective_target
        eff_target = _resolve_effective_target(stored, target)
        repo_file = self._tt_config.configs_dir / config / "files" / stored
        sys_file = Path.home() / eff_target
        if not repo_file.exists():
            return
        if repo_file.is_dir() and sys_file.is_dir():
            deletions = _dir_deletions(repo_file, sys_file)
            if deletions:
                self.app.push_screen(
                    ConfirmDeletionsScreen(
                        f"Apply TT → ~/{eff_target}",
                        deletions,
                        "delete and apply",
                    ),
                    callback=lambda ok: self._do_apply(config, stored, target) if ok else None,
                )
                return
        self._do_apply(config, stored, target)

    def _do_apply(self, config: str, stored: str, target: str) -> None:
        import shutil
        from tui.core.config import _resolve_effective_target
        repo_file = self._tt_config.configs_dir / config / "files" / stored
        sys_file = Path.home() / _resolve_effective_target(stored, target)
        if not repo_file.exists():
            return
        if repo_file.is_dir():
            sys_file.parent.mkdir(parents=True, exist_ok=True)
            if sys_file.exists():
                if sys_file.is_dir():
                    shutil.rmtree(sys_file)
                else:
                    sys_file.unlink()
            shutil.copytree(repo_file, sys_file)
        else:
            sys_file.parent.mkdir(parents=True, exist_ok=True)
            sys_file.write_bytes(repo_file.read_bytes())
        self._refresh_files()
        self._show_diff(config, stored, target)

    def action_update_tooltamer(self) -> None:
        """Copy system file/dir to repo. On inherited entries, ask whether to
        write to the inherited config (affects all hosts) or create a
        host-local override."""
        sel = self._get_selected()
        if not sel:
            return
        config, stored, target = sel
        from tui.core.config import _resolve_effective_target
        sys_file = Path.home() / _resolve_effective_target(stored, target)
        if not sys_file.exists():
            return
        host = self._system.hostname
        if config != host:
            self.app.push_screen(
                CaptureChoiceScreen(config, host, _resolve_effective_target(stored, target)),
                callback=lambda choice: self._capture_with_check(config, stored, target, choice),
            )
            return
        self._capture_with_check(config, stored, target, "parent")

    def _capture_with_check(self, config: str, stored: str, target: str, choice: str | None) -> None:
        if choice not in ("parent", "override"):
            return
        from tui.core.config import _resolve_effective_target
        eff_target = _resolve_effective_target(stored, target)
        sys_path = Path.home() / eff_target
        host = self._system.hostname
        if choice == "override":
            dest_path = self._tt_config.configs_dir / host / "files" / stored
        else:
            dest_path = self._tt_config.configs_dir / config / "files" / stored
        if sys_path.is_dir() and dest_path.is_dir():
            deletions = _dir_deletions(sys_path, dest_path)
            if deletions:
                target_label = host if choice == "override" else config
                self.app.push_screen(
                    ConfirmDeletionsScreen(
                        f"Capture ~/{eff_target} → '{target_label}'",
                        deletions,
                        "delete and capture",
                    ),
                    callback=lambda ok: self._do_capture(config, stored, target, choice) if ok else None,
                )
                return
        self._do_capture(config, stored, target, choice)

    def _do_capture(self, config: str, stored: str, target: str, choice: str | None) -> None:
        import shutil

        if choice not in ("parent", "override"):
            return
        from tui.core.config import _resolve_effective_target
        sys_path = Path.home() / _resolve_effective_target(stored, target)
        if not sys_path.exists():
            return
        host = self._system.hostname
        if choice == "override":
            dest_config = host
            dest_path = self._tt_config.configs_dir / host / "files" / stored
        else:
            dest_config = config
            dest_path = self._tt_config.configs_dir / config / "files" / stored
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if sys_path.is_dir():
            if dest_path.exists():
                if dest_path.is_dir():
                    shutil.rmtree(dest_path)
                else:
                    dest_path.unlink()
            shutil.copytree(sys_path, dest_path)
        else:
            dest_path.write_bytes(sys_path.read_bytes())
        if choice == "override":
            self._tt_config.add_file_mapping(host, stored, target)
        self._refresh_files()
        self._show_diff(dest_config, stored, target)

    def action_remove_from_tt(self) -> None:
        """Remove file from TT config (stop managing it)."""
        sel = self._get_selected()
        if not sel:
            return
        config, stored, target = sel
        from tui.core.config import _resolve_effective_target
        eff_target = _resolve_effective_target(stored, target)
        self._tt_config.remove_file_mapping(config, stored, target)
        log = self.query_one("#file-diff", RichLog)
        log.clear()
        log.write(Text(f"Removed ~/{eff_target} from {config}", style="green"))
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
        from tui.core.config import _resolve_effective_target
        eff_target = _resolve_effective_target(stored, target)
        log = self.query_one("#file-diff", RichLog)
        log.clear()
        log.write(Text(f"Copied ~/{eff_target} to {host} config", style="green"))
        log.write(Text(f"Was inherited from {config}, now local.", style="dim"))
        log.write(Text("Edit the local copy, then u=update TT.", style="dim"))
        self._refresh_files()

    def action_add_file(self) -> None:
        """Add a new file or directory to TT. Uses fzf when available."""
        import shutil as _sh

        if _sh.which("fzf"):
            picked = self._pick_with_fzf()
            if picked is None:
                return
            self.app.push_screen(
                AddConfigPickScreen(self._tt_config, self._system, picked),
                callback=lambda _: self._refresh_files(),
            )
        else:
            self.app.push_screen(AddFileScreen(self._tt_config, self._system))

    def _pick_with_fzf(self) -> Path | None:
        """Suspend the TUI, run fzf to pick a file or directory under ~, return
        the chosen path (or None if cancelled)."""
        import shutil as _sh
        import subprocess

        home = str(Path.home())
        if _sh.which("fd"):
            list_cmd = [
                "fd", "--hidden", "--exclude", ".git",
                "--type", "f", "--type", "d",
                ".", home,
            ]
        else:
            list_cmd = [
                "find", home,
                "(", "-type", "f", "-o", "-type", "d", ")",
                "-not", "-path", "*/.git/*",
            ]

        with self.app.suspend():
            try:
                lister = subprocess.Popen(list_cmd, stdout=subprocess.PIPE)
                result = subprocess.run(
                    [
                        "fzf",
                        "--prompt=add to TT> ",
                        "--header=pick a file or directory under ~",
                        "--height=80%",
                    ],
                    stdin=lister.stdout, capture_output=True, text=True,
                )
                if lister.stdout:
                    lister.stdout.close()
                lister.wait()
            except FileNotFoundError:
                return None

        if result.returncode != 0:
            return None
        picked = result.stdout.strip()
        if not picked:
            return None
        path = Path(picked)
        if not path.exists():
            self.notify(f"Path does not exist: {picked}", severity="error")
            return None
        try:
            path.relative_to(Path.home())
        except ValueError:
            self.notify("Only paths under ~ can be added", severity="error")
            return None
        return path

    def on_screen_resume(self) -> None:
        """Refresh when returning from add/move screens."""
        self._refresh_files()

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


class ConfirmDeletionsScreen(ModalScreen[bool]):
    """Confirm a directory sync that would delete files on the destination."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("n", "cancel", "No"),
        ("y", "confirm", "Yes"),
    ]

    DEFAULT_CSS = """
    ConfirmDeletionsScreen {
        align: center middle;
    }
    #confirm-del-dialog {
        width: 90;
        height: auto;
        max-height: 80%;
        border: round $warning;
        background: $surface;
        padding: 1 2;
    }
    #confirm-del-list {
        height: 20;
        max-height: 20;
        border: round $panel;
    }
    """

    def __init__(self, header: str, deletions: list[str], proceed_label: str):
        super().__init__()
        self._header = header
        self._deletions = deletions
        self._proceed_label = proceed_label

    def compose(self) -> ComposeResult:
        with Container(id="confirm-del-dialog"):
            yield Label(Text(self._header, style="bold yellow"))
            yield Label(Text(""))
            yield Label(Text(
                f"{len(self._deletions)} file(s) will be deleted on the destination:",
                style="bold",
            ))
            yield RichLog(id="confirm-del-list", wrap=False, markup=False)
            yield Label(Text(""))
            yield Label(Text(f"y={self._proceed_label}    n/Esc=cancel", style="dim"))

    def on_mount(self) -> None:
        log = self.query_one("#confirm-del-list", RichLog)
        for path in self._deletions[:200]:
            log.write(Text(f"  - {path}", style="red"))
        if len(self._deletions) > 200:
            log.write(Text(f"  ... and {len(self._deletions) - 200} more", style="dim"))

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class AddConfigPickScreen(ModalScreen[str | None]):
    """Pick which config to add a previously-chosen file/directory to."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    AddConfigPickScreen {
        align: center middle;
    }
    #add-config-dialog {
        width: 70;
        height: auto;
        max-height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, tt_config: TTConfig, system: SystemInfo, source: Path):
        super().__init__()
        self._tt_config = tt_config
        self._system = system
        self._source = source

    def compose(self) -> ComposeResult:
        rel = str(self._source.relative_to(Path.home()))
        kind = "dir" if self._source.is_dir() else "file"
        suffix = "/" if self._source.is_dir() else ""
        with Container(id="add-config-dialog"):
            yield Label(Text.assemble(
                ("Add ", "bold"),
                (f"~/{rel}{suffix}", "cyan"),
                (f"  ({kind})", "dim"),
            ))
            yield Label(Text(""))
            yield Label(Text("Select target config:", style="bold"))
            options = []
            host = self._system.hostname
            for cfg in self._tt_config.list_configs():
                tag = ""
                if cfg == host:
                    tag = " [green][host][/]"
                elif cfg == "common":
                    tag = " [cyan][common][/]"
                options.append(Option(f"{cfg}{tag}", id=cfg))
            yield OptionList(*options)
            yield Label(Text(""))
            yield Label(Text("Esc=cancel", style="dim"))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        import shutil

        dest = str(event.option.id)
        rel_path = str(self._source.relative_to(Path.home()))
        dest_target = self._tt_config.configs_dir / dest / "files" / rel_path
        dest_target.parent.mkdir(parents=True, exist_ok=True)
        if self._source.is_dir():
            if dest_target.exists():
                shutil.rmtree(dest_target)
            shutil.copytree(self._source, dest_target)
        else:
            dest_target.write_bytes(self._source.read_bytes())
        self._tt_config.add_file_mapping(dest, rel_path, rel_path)
        self.dismiss(dest)

    def action_cancel(self) -> None:
        self.dismiss(None)


class CaptureChoiceScreen(ModalScreen[str | None]):
    """Ask user whether to capture changes to the inherited config or create
    a local host override."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("p", "pick('parent')", "Parent"),
        ("o", "pick('override')", "Override"),
    ]

    DEFAULT_CSS = """
    CaptureChoiceScreen {
        align: center middle;
    }
    #capture-choice-dialog {
        width: 70;
        height: auto;
        max-height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, parent_config: str, host: str, eff_target: str):
        super().__init__()
        self._parent_config = parent_config
        self._host = host
        self._eff_target = eff_target

    def compose(self) -> ComposeResult:
        with Container(id="capture-choice-dialog"):
            yield Label(Text.assemble(
                ("Capture ", "bold"),
                (f"~/{self._eff_target}", "cyan"),
                (" — file is inherited from ", ""),
                (self._parent_config, "yellow"),
                (".", ""),
            ))
            yield Label(Text(""))
            yield Label(Text("Where should the current system content be saved?", style="bold"))
            yield Label(Text(""))
            yield OptionList(
                Option(
                    f"Write to '{self._parent_config}' (affects all hosts using it)",
                    id="parent",
                ),
                Option(
                    f"Create local override in '{self._host}' (only this host)",
                    id="override",
                ),
            )
            yield Label(Text(""))
            yield Label(Text("Esc=cancel  p=parent  o=override", style="dim"))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.id))

    def action_pick(self, choice: str) -> None:
        self.dismiss(choice)

    def action_cancel(self) -> None:
        self.dismiss(None)


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


class AddFileScreen(Screen):
    """Browse home directory and add a file or directory to TT management."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("plus", "pick_highlighted", "Pick (file or dir)"),
    ]

    DEFAULT_CSS = """
    AddFileScreen {
        layout: horizontal;
    }
    #file-browser-pane {
        width: 2fr;
        border: round $accent;
        padding: 0 1;
    }
    #file-browser-pane DirectoryTree {
        height: 1fr;
    }
    #file-config-pane {
        width: 1fr;
        border: round $primary;
        padding: 1 2;
    }
    """

    def __init__(self, tt_config: TTConfig, system: SystemInfo):
        super().__init__()
        self._tt_config = tt_config
        self._system = system
        self._selected_path: Path | None = None

    def compose(self) -> ComposeResult:
        from textual.widgets import DirectoryTree

        yield Header()
        with Container(id="file-browser-pane"):
            yield Label(Text("Browse ~ — Enter picks a file, '+' picks file or directory", style="bold"))
            yield DirectoryTree(str(Path.home()), id="dir-tree")
        with Container(id="file-config-pane"):
            yield Label(Text("Select config:", style="bold"))
            yield Label(Text("", style="dim"), id="selected-file-label")
            yield Label(Text(""))
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
        yield Footer()

    def on_directory_tree_file_selected(self, event) -> None:
        """Enter on a file in the tree picks it."""
        self._set_selected(Path(event.path))

    def action_pick_highlighted(self) -> None:
        """Pick the currently highlighted node — works for files and directories."""
        from textual.widgets import DirectoryTree
        tree = self.query_one("#dir-tree", DirectoryTree)
        node = tree.cursor_node
        if node is None or node.data is None:
            return
        path = Path(node.data.path)
        self._set_selected(path)
        self.query_one("#config-list", OptionList).focus()

    def _set_selected(self, path: Path) -> None:
        self._selected_path = path
        try:
            rel = str(path.relative_to(Path.home()))
        except ValueError:
            rel = str(path)
        suffix = "/" if path.is_dir() else ""
        kind = "dir" if path.is_dir() else "file"
        label = self.query_one("#selected-file-label", Label)
        label.update(Text(f"Selected ({kind}): ~/{rel}{suffix}", style="cyan"))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        import shutil

        if self._selected_path is None:
            return
        sys_path = self._selected_path
        if not sys_path.exists():
            return
        try:
            rel_path = str(sys_path.relative_to(Path.home()))
        except ValueError:
            return

        dest = str(event.option.id)
        stored = rel_path
        dest_target = self._tt_config.configs_dir / dest / "files" / stored
        dest_target.parent.mkdir(parents=True, exist_ok=True)
        if sys_path.is_dir():
            if dest_target.exists():
                shutil.rmtree(dest_target)
            shutil.copytree(sys_path, dest_target)
        else:
            dest_target.write_bytes(sys_path.read_bytes())
        self._tt_config.add_file_mapping(dest, stored, rel_path)
        self.app.pop_screen()

    def action_go_back(self) -> None:
        self.app.pop_screen()
