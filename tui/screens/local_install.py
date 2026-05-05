"""Manage the per-config local_install.sh scripts."""

import os
import platform
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from rich.text import Text

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, RichLog

from tui.core.config import TTConfig
from tui.core.system import SystemInfo


SCRIPT_NAME = "local_install.sh"
DEFAULT_TEMPLATE = (
    "# local_install.sh — sourced by tt during sync (in include order:\n"
    "# common, then includes, then host).\n"
    "# Use it for steps that aren't expressed by package or file mappings.\n"
    "\n"
)


class LocalInstallScreen(Screen):
    """View, edit, create, remove and execute local_install.sh per config."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("e", "edit", "Edit"),
        ("n", "create", "Create"),
        ("r", "remove", "Remove"),
        ("x", "execute", "Execute Chain"),
        ("tab", "switch_pane", "Switch Pane"),
    ]

    def __init__(self, tt_config: TTConfig, system: SystemInfo):
        super().__init__()
        self._tt_config = tt_config
        self._system = system

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="local-install-screen"):
            with Container(id="local-install-list-pane"):
                yield Label(
                    f"local_install.sh per config  [dim]OK=present  --=missing[/]",
                    classes="section-title",
                )
                yield DataTable(id="local-install-table")
            with Container(id="local-install-content-pane"):
                yield Label("Content", classes="section-title")
                yield RichLog(id="local-install-content", wrap=False, markup=False)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#local-install-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("St", "Config", "Lines")
        self._load_table()
        log = self.query_one("#local-install-content", RichLog)
        log.write(Text("Select a config to view its local_install.sh.", style="dim"))
        log.write(Text(""))
        log.write(Text("Keybindings:", style="bold"))
        log.write(Text("  e  Edit in $EDITOR (creates if missing)", style="dim"))
        log.write(Text("  n  Create empty script", style="dim"))
        log.write(Text("  r  Remove script", style="dim"))
        log.write(Text("  x  Execute the full chain (common → includes → host)", style="dim"))
        log.write(Text("  Esc  Back", style="dim"))

    def _load_table(self) -> None:
        table = self.query_one("#local-install-table", DataTable)
        table.clear()
        host = self._system.hostname
        # Show in execution order: common, includes (in order), host, then any
        # other configs.
        chain = self._tt_config.resolve_chain(host)
        rest = [c for c in self._tt_config.list_configs() if c not in chain]
        all_cfgs = chain + rest

        for cfg in all_cfgs:
            path = self._script_path(cfg)
            exists = path.exists()
            lines = ""
            if exists:
                try:
                    lines = str(sum(1 for _ in path.read_text().splitlines()))
                except OSError:
                    lines = "?"

            st = Text("OK") if exists else Text("--")
            if exists:
                st.stylize("green")
            else:
                st.stylize("red")

            cfg_text = Text(cfg)
            if cfg == host:
                cfg_text.stylize("bold green")
            elif cfg == "common":
                cfg_text.stylize("cyan")
            elif cfg in chain:
                cfg_text.stylize("blue")
            else:
                cfg_text.stylize("dim")

            table.add_row(st, cfg_text, Text(lines, style="dim"), key=cfg)

    def _script_path(self, config: str) -> Path:
        return self._tt_config.configs_dir / config / SCRIPT_NAME

    def _selected_config(self) -> str | None:
        table = self.query_one("#local-install-table", DataTable)
        row_idx = table.cursor_row
        if row_idx is None:
            return None
        keys = list(table.rows.keys())
        if row_idx >= len(keys):
            return None
        return str(keys[row_idx].value)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None:
            return
        self._show_content(str(event.row_key.value))

    def _show_content(self, config: str) -> None:
        log = self.query_one("#local-install-content", RichLog)
        log.clear()
        path = self._script_path(config)
        log.write(Text(f"{config} — {path}", style="bold"))
        if config in self._tt_config.resolve_chain(self._system.hostname):
            log.write(Text(
                "Active for this host (sourced during sync).",
                style="green",
            ))
        else:
            log.write(Text(
                "Not in this host's include chain — would not run on sync.",
                style="dim yellow",
            ))
        log.write(Text(""))
        if not path.exists():
            log.write(Text("No script. Press 'e' or 'n' to create one.", style="red"))
            return
        try:
            content = path.read_text()
        except OSError as err:
            log.write(Text(f"Cannot read: {err}", style="red"))
            return
        if not content.strip():
            log.write(Text("(empty)", style="dim"))
            return
        for line in content.splitlines():
            styled = Text(line)
            stripped = line.lstrip()
            if stripped.startswith("#"):
                styled.stylize("dim")
            log.write(styled)

    def action_go_back(self) -> None:
        self.dismiss(None)

    def action_edit(self) -> None:
        cfg = self._selected_config()
        if cfg is None:
            return
        path = self._script_path(cfg)
        created = False
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(DEFAULT_TEMPLATE)
            created = True
        editor = os.environ.get("EDITOR", "vi")
        with self.app.suspend():
            try:
                subprocess.run([editor, str(path)])
            except FileNotFoundError:
                self.app.notify(f"Editor not found: {editor}", severity="error")
                if created:
                    try:
                        path.unlink()
                    except OSError:
                        pass
                return
        self._load_table()
        self._show_content(cfg)

    def action_create(self) -> None:
        cfg = self._selected_config()
        if cfg is None:
            return
        path = self._script_path(cfg)
        if path.exists():
            self.notify("Script already exists", severity="warning")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_TEMPLATE)
        self._load_table()
        self._show_content(cfg)

    def action_remove(self) -> None:
        cfg = self._selected_config()
        if cfg is None:
            return
        path = self._script_path(cfg)
        if not path.exists():
            return
        try:
            path.unlink()
        except OSError as err:
            self.notify(f"Cannot remove: {err}", severity="error")
            return
        self._load_table()
        self._show_content(cfg)

    def action_execute(self) -> None:
        """Source every local_install.sh in the host's include chain in a
        single bash shell — mirrors `bin/tt:runLocalInstall`. Loads tt's
        include.sh first so log/logn/err/warn and the standard env vars are
        available, just like during a real `tt` run."""
        chain = self._tt_config.resolve_chain(self._system.hostname)
        existing = [(c, self._script_path(c)) for c in chain]
        present = [(c, p) for c, p in existing if p.exists()]
        if not present:
            self.notify("No local_install.sh in the host's chain", severity="warning")
            return

        include_sh = self._find_include_sh()
        tmp = Path(tempfile.mkdtemp(prefix="tt-tui-exec-"))
        try:
            preamble: list[str] = [
                "set +e",
                f"export TMP={shlex.quote(str(tmp))}",
                'mkdir -p "$TMP"',
                f"export HOST={shlex.quote(self._system.hostname)}",
                f"export OS_TYPE={shlex.quote(platform.system())}",
                f"export INSTALLER={shlex.quote(self._system.installer)}",
                f"export BASE={shlex.quote(str(self._tt_config.base))}/",
            ]
            if include_sh is not None:
                preamble.append(f"source {shlex.quote(str(include_sh))}")
                # include.sh registers `trap cleanup EXIT QUIT TERM` and the
                # cleanup function does `rm -rf $TMP`. We manage TMP ourselves,
                # so clear the trap to avoid surprises and double-cleanup.
                preamble.append("trap - EXIT QUIT TERM")
            else:
                # Minimal fallback: at least define log/logn so scripts don't
                # crash on the very first line.
                preamble.extend([
                    "logn() { echo -ne \"$1\"; }",
                    "log()  { echo -e  \"$1\"; }",
                    "err()  { echo -e  \"error: $1\" >&2; }",
                    "warn() { echo -e  \"warning: $1\" >&2; }",
                    "logf() { echo -e  \"$1\"; }",
                ])

            body: list[str] = []
            for cfg, path in existing:
                if path.exists():
                    qpath = shlex.quote(str(path))
                    body.append(f'echo; echo "--- {cfg}: sourcing {path} ---"')
                    body.append(f"source {qpath}")
                    body.append(f'echo "--- {cfg}: done ---"')
                else:
                    body.append(f'echo "--- {cfg}: no local_install.sh, skipped ---"')

            program = "\n".join(preamble + body)

            with self.app.suspend():
                if include_sh is None:
                    print("\n[warn] tt's include.sh not found — running with minimal helpers only.\n", flush=True)
                print(f"\nExecuting chain: {' -> '.join(c for c, _ in existing)}\n", flush=True)
                try:
                    subprocess.run(["bash", "-c", program])
                except FileNotFoundError:
                    print("bash not found", flush=True)
                input("\n[press Enter to return to TUI] ")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        self._load_table()
        cfg = self._selected_config()
        if cfg is not None:
            self._show_content(cfg)

    def _find_include_sh(self) -> Path | None:
        """Locate tt's include.sh — used to bring log/logn/err/warn and the
        standard env vars into scope before sourcing local_install.sh."""
        candidates: list[Path] = []
        # Repo-relative (TUI lives at <repo>/tui/screens/, include.sh at <repo>/bin/)
        candidates.append(Path(__file__).resolve().parents[2] / "bin" / "include.sh")
        # Beside `tt` in PATH
        tt_bin = shutil.which("tt")
        if tt_bin:
            candidates.append(Path(tt_bin).resolve().parent / "include.sh")
        # Common install location next to TT_BASE
        candidates.append(self._tt_config.base.parent / "bin" / "include.sh")
        for c in candidates:
            if c.is_file():
                return c
        return None

    def action_switch_pane(self) -> None:
        table = self.query_one("#local-install-table", DataTable)
        log = self.query_one("#local-install-content", RichLog)
        if table.has_focus:
            log.focus()
        else:
            table.focus()
