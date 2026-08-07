"""Package manager screen with hierarchy view and move/copy."""

import concurrent.futures

from rich.text import Text

from textual import work
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
)
from textual.worker import get_current_worker

from tui.core.config import TTConfig
from tui.core.system import SystemInfo
from tui.screens._dest_picker import DestPickerScreen


class BulkActionConfirmScreen(ModalScreen[bool]):
    """Confirm a bulk action, listing which marked packages it applies to
    and which ones are skipped (with the reason)."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("n", "cancel", "No"),
        ("y", "confirm", "Yes"),
    ]

    DEFAULT_CSS = """
    BulkActionConfirmScreen {
        align: center middle;
    }
    #bulk-confirm-dialog {
        width: 80;
        height: auto;
        max-height: 80%;
        border: round $warning;
        background: $surface;
        padding: 1 2;
    }
    #bulk-confirm-list {
        height: 20;
        max-height: 20;
        border: round $panel;
    }
    """

    def __init__(
        self,
        action_label: str,
        valid: list[tuple[str, str]],
        skipped: list[tuple[str, str, str]],
    ):
        super().__init__()
        self._action_label = action_label
        self._valid = valid
        self._skipped = skipped

    def compose(self) -> ComposeResult:
        total = len(self._valid) + len(self._skipped)
        with Container(id="bulk-confirm-dialog"):
            yield Label(
                Text(
                    f"{self._action_label} — {total} marked package(s)",
                    style="bold yellow",
                )
            )
            yield Label(Text(""))
            yield RichLog(id="bulk-confirm-list", wrap=False, markup=False)
            yield Label(Text(""))
            yield Label(
                Text(
                    f"y={self._action_label.lower()}    n/Esc=cancel", style="dim"
                )
            )

    def on_mount(self) -> None:
        log = self.query_one("#bulk-confirm-list", RichLog)
        log.write(Text(f"{len(self._valid)} will be processed:", style="bold"))
        for config, pkg in self._valid:
            log.write(Text(f"  + {pkg} ({config})", style="green"))
        if self._skipped:
            log.write(Text(""))
            log.write(Text(f"{len(self._skipped)} skipped:", style="bold"))
            for config, pkg, reason in self._skipped:
                log.write(Text(f"  - {pkg} ({config}): {reason}", style="yellow"))

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class PackageScreen(Screen):
    """View and manage packages across the config hierarchy."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("m", "move_package", "Move"),
        ("c", "copy_package", "Copy"),
        ("i", "install_package", "Install"),
        ("x", "uninstall_package", "Uninstall"),
        ("r", "remove_from_config", "Remove from Config"),
        ("u", "uninstall_and_remove", "Uninstall + Remove from Config"),
        ("a", "add_to_config", "Add to Config"),
        ("d", "toggle_hide_deps", "Hide deps"),
        ("space", "toggle_mark", "Mark"),
        ("slash", "focus_search", "Search"),
        ("tab", "switch_pane", "Switch Pane"),
        ("pageup", "page_up", "Page up"),
        ("pagedown", "page_down", "Page down"),
    ]

    # Human-readable names of the bulk actions, used in the confirm dialog
    # and in the result log.
    BULK_LABELS = {
        "uninstall": "Uninstall",
        "move": "Move to config",
        "remove": "Remove from config",
        "uninstall_remove": "Uninstall + remove from config",
    }

    def __init__(self, tt_config: TTConfig, system: SystemInfo):
        super().__init__()
        self._tt_config = tt_config
        self._system = system
        self._all_rows: list[tuple[str, str, str, str, bool]] = []  # status, pkg, tag, key, is_dep
        self._dep_packages: set[str] = set()
        self._hide_deps: bool = False
        # Row keys ("cfg:pkg" / "_extra_:pkg") of rows marked for a bulk
        # action. Kept outside the table so marks survive reloads and
        # filter changes.
        self._marked: set[str] = set()
        # True while _run_pkg_action/_run_bulk_action's worker is running.
        # Both mutate config files (read-modify-write, no locking) and run
        # real install/uninstall commands — starting a second one before
        # the first finishes could race on the same config file or fire
        # off duplicate uninstalls. Checked (and set) on the main thread
        # from the action_* trigger methods, cleared from the worker via
        # call_from_thread once it's done.
        self._action_busy: bool = False
        # True while _load_extra_deps' background scan is running. Shown
        # in the title so a blank "Dep" cell on an "extra" package reads
        # as "not checked yet", not "confirmed not a dependency" — the
        # scan can take a while on a config with hundreds of untracked
        # packages (see _extra_required_deps).
        self._extra_deps_scanning: bool = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="pkg-screen"):
            with Container(id="pkg-list-pane"):
                yield Label(
                    "Packages  [dim]OK=installed  !!=missing  ++=extra  --=unknown  D=dependency[/]",
                    classes="section-title",
                    id="pkg-title",
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
        table.add_columns("✓", "St", "Package", "Dep", "Config")
        self._dep_packages = self._safe_dep_packages()
        self._load_packages()
        self._start_extra_deps_scan()
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
        log.write(Text("  u  Uninstall and remove from config", style="dim"))
        log.write(Text("  a  Add new package to config", style="dim"))
        log.write(Text("  d  Toggle hide dependency-only packages", style="dim"))
        log.write(Text("  Space  Mark/unmark row for bulk actions", style="dim"))
        log.write(
            Text("       x/m/r/u act on all marked rows", style="dim")
        )
        log.write(Text("  /  Filter packages", style="dim"))
        log.write(Text("  Esc  Back to dashboard", style="dim"))

    def _safe_dep_packages(self) -> set[str]:
        """Dependency-only package names from the cheap, single-call signal
        (list_dependency_packages — install *reason*, apt-mark auto vs.
        manual), or an empty set on any failure. Fast enough to run
        synchronously on the UI thread, unlike _extra_required_deps()
        below — see _load_extra_deps() for why that one is a background
        worker instead of being unioned in here."""
        try:
            return self._system.list_dependency_packages()
        except Exception:
            return set()

    def _start_extra_deps_scan(self) -> None:
        """Set _extra_deps_scanning before kicking off the background
        worker (not inside it — a @work call returns immediately, and
        the thread may not start running for a moment, so setting the
        flag here on the main thread is what makes the title update
        show "checking..." right away instead of lagging behind)."""
        self._extra_deps_scanning = True
        self._update_title()
        self._load_extra_deps()

    @work(thread=True, exclusive=True, group="extra-deps")
    def _load_extra_deps(self) -> None:
        """Background counterpart to _safe_dep_packages(): fills in
        _extra_required_deps() — the structural signal (currently required
        by another installed package) for untracked "extra" packages,
        which list_dependency_packages() alone misses (the json-glib
        report) — and merges any hits into _dep_packages once done.

        Deliberately NOT run synchronously like the rest of _dep_packages:
        get_required_by() is one subprocess call per untracked package, and
        running that inline in on_mount()/_refresh_packages() blocked
        opening the screen (and every hide-deps toggle / post-action
        refresh) for as long as the scan took — see the "Package-View
        hängt sich auf" report. exclusive=True so a second refresh (e.g.
        quickly toggling hide-deps, or several uninstalls in a row)
        cancels a still-running scan instead of piling up concurrent ones.

        group="extra-deps" — its own group, distinct from
        _show_package_info's default-group exclusivity: @work's default
        group is the literal string "default" for every method that
        doesn't set one, so without this override, highlighting a row
        (which fires _show_package_info) would cancel a still-running
        extras scan out from under it, and vice versa. That's exactly
        what silently broke the "D" tag for extras in practice — the
        table populates (mounting doesn't hang anymore), but
        _load_extra_deps never reaches its call_from_thread because the
        auto-highlighted first row's _show_package_info worker starts
        first and cancels it."""
        worker = get_current_worker()
        extra_deps = self._extra_required_deps(should_stop=lambda: worker.is_cancelled)
        if worker.is_cancelled:
            return
        self.app.call_from_thread(self._merge_extra_deps, extra_deps)

    def _merge_extra_deps(self, extra_deps: set[str]) -> None:
        self._dep_packages |= extra_deps
        self._extra_deps_scanning = False
        self._redraw_rows()

    def _extra_required_deps(self, should_stop=None) -> set[str]:
        """Installed packages that are in no tracked config ("extra") but
        are structurally required by another installed package right now —
        they'd otherwise look like standalone extra tools in the overview
        when they're really just dependencies list_dependency_packages()
        missed. get_required_by() is one subprocess call per package, so
        this is deliberately bounded to the (usually small) set of extras
        list_dependency_packages() didn't already flag (self._dep_packages
        — no point re-checking those structurally too), not run for every
        package in the list. Empty on any failure — display-only, must
        never crash the screen.

        The remaining per-package calls run in a thread pool: on a real
        machine with hundreds of untracked packages, doing this one at a
        time made the "D" tag take minutes to show up (still running in
        the background, so it didn't hang the screen — but it looked to
        the user like those packages just weren't dependencies). Mirrors
        the same fix already applied to tui/cleanup_deps.py.

        should_stop: optional zero-arg callable checked as each parallel
        check completes — lets _load_extra_deps() bail out of a still-
        running scan as soon as it's superseded (e.g. a fast series of
        uninstalls, or hide-deps toggled repeatedly) instead of waiting
        for every remaining package, and pending-but-not-yet-started
        checks are cancelled outright."""
        try:
            installed = set(self._system.list_installed_packages())
            if not installed:
                return set()
            effective: set[str] = set()
            for cfg in self._tt_config.resolve_chain(self._system.hostname):
                effective.update(self._tt_config.get_packages(cfg, self._system.installer))
            extras = installed - effective - self._dep_packages
            if not extras:
                return set()

            found: set[str] = set()
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=8)
            try:
                futures = {
                    pool.submit(self._system.get_required_by, pkg): pkg
                    for pkg in extras
                }
                for future in concurrent.futures.as_completed(futures):
                    pkg = futures[future]
                    try:
                        if future.result():
                            found.add(pkg)
                    except Exception:
                        pass
                    if should_stop is not None and should_stop():
                        break
            finally:
                # cancel_futures drops anything not yet started; already-
                # running calls finish on their own (there's no way to
                # force-kill a subprocess.run() mid-flight from here) but
                # we don't wait around for them.
                pool.shutdown(wait=False, cancel_futures=True)
            return found
        except Exception:
            return set()

    def _safe_required_by(self, package: str) -> list[str]:
        """Installed packages that currently require `package`, or an
        empty list on any failure — the check must never crash or block
        an uninstall attempt on its own."""
        try:
            return self._system.get_required_by(package)
        except Exception:
            return []

    def _refresh_packages(self) -> None:
        """Reload packages preserving the current filter. Also refreshes
        the cached dependency set (the cheap part, synchronously —
        _load_extra_deps() below fills in the rest in the background),
        since installing/uninstalling a package can change which packages
        are dependency-only.

        Called via call_from_thread from a background worker once an
        action finishes — guarded there by is_cancelled, but that check
        and this call aren't atomic, so a NoMatches from querying a
        screen that got unmounted in between (Esc right as the action
        wraps up) is caught here too, rather than propagating back into
        the worker thread and crashing it."""
        try:
            current_filter = self.query_one("#pkg-filter", Input).value
        except NoMatches:
            return
        self._dep_packages = self._safe_dep_packages()
        self._load_packages(filter_text=current_filter)
        self._start_extra_deps_scan()

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
                is_dep = pkg in self._dep_packages
                self._all_rows.append((status, pkg, tag, f"{cfg}:{pkg}", is_dep))

        # Add extra packages (installed but not in any config)
        if installed:
            extras = sorted(installed - effective_set)
            for pkg in extras:
                is_dep = pkg in self._dep_packages
                self._all_rows.append(("++", pkg, "system", f"_extra_:{pkg}", is_dep))

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

        for status, pkg, tag, key, is_dep in self._all_rows:
            if status_filter and status != status_filter:
                continue
            if name_filter and name_filter not in pkg.lower():
                continue
            if self._hide_deps and is_dep:
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

            dep_text = Text("D", style="dim") if is_dep else Text("")
            mark_text = (
                Text("✓", style="bold green") if key in self._marked else Text("")
            )
            table.add_row(mark_text, st, Text(pkg), dep_text, cfg_text, key=key)

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

    @work(thread=True, exclusive=True)
    def _show_package_info(self, config: str, package: str) -> None:
        worker = get_current_worker()
        info_text = self._system.get_package_info(package)
        if worker.is_cancelled:
            # A newer row got highlighted while we were still fetching
            # info for this one — exclusive=True only requests
            # cancellation of a thread worker, it doesn't stop it, so this
            # check is what actually prevents a superseded worker from
            # doing the second (also slow) subprocess call below and then
            # writing stale info into the shared RichLog.
            return
        log = self.query_one("#pkg-info", RichLog)
        self.app.call_from_thread(log.clear)

        self.app.call_from_thread(log.write, Text(package, style="bold"))
        self.app.call_from_thread(log.write, Text(f"Config: {config}", style="cyan"))

        # Show tap if from a third-party tap
        tap = self._system.get_package_tap(package)
        if worker.is_cancelled:
            return
        if tap:
            self.app.call_from_thread(log.write, Text(f"Tap: {tap}", style="dim"))

        installed = set()
        try:
            installed = set(self._system.list_installed_packages())
        except Exception:
            pass

        # Structural reverse-dependency check — distinct from the "D"
        # (dependency-only) tag, which only reflects install *reason*
        # (apt-mark auto vs. manual). A package can be "manual" (no "D"
        # tag) and still be required by another installed package right
        # now; surface that here, before the user tries to uninstall it,
        # rather than only as a failure message afterwards. Only relevant
        # for installed packages — skip the subprocess call otherwise.
        if package in installed:
            required_by = self._safe_required_by(package)
            if worker.is_cancelled:
                return
            if required_by:
                self.app.call_from_thread(
                    log.write,
                    Text(
                        f"⚠ Required by: {', '.join(required_by)}",
                        style="bold red",
                    ),
                )

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

        self.app.call_from_thread(log.write, Text(""))
        if package not in installed:
            self.app.call_from_thread(
                log.write, Text("i=install  r=remove from config  m=move  c=copy", style="dim")
            )
        else:
            self.app.call_from_thread(
                log.write,
                Text(
                    "x=uninstall  u=uninstall+remove from config  "
                    "r=remove from config  m=move  c=copy",
                    style="dim",
                ),
            )

    def action_go_back(self) -> None:
        self.dismiss(None)

    def _get_selected_row_key(self) -> str | None:
        """Raw row key ("cfg:pkg") of the row under the cursor."""
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
        return key

    def _get_selected_key(self) -> tuple[str, str] | None:
        key = self._get_selected_row_key()
        if key is None:
            return None
        return key.split(":", 1)

    def action_toggle_mark(self) -> None:
        """Toggle the bulk-action mark on the row under the cursor."""
        key = self._get_selected_row_key()
        if key is None:
            return
        if key in self._marked:
            self._marked.discard(key)
        else:
            self._marked.add(key)
        self._redraw_rows()

    def _redraw_rows(self) -> None:
        """Re-render the table from the cached rows (no subprocess calls),
        keeping the cursor where it was."""
        table = self.query_one("#pkg-table", DataTable)
        cursor = table.cursor_row
        self._load_packages(filter_text=self.query_one("#pkg-filter", Input).value)
        if cursor is not None and 0 <= cursor < table.row_count:
            table.move_cursor(row=cursor)
        self._update_title()

    def _update_title(self) -> None:
        """Show the number of marked rows, and whether the background
        dependency scan for "extra" packages is still running, in the
        list-pane title."""
        count = len(self._marked)
        prefix = f"Packages ({count} marked)" if count else "Packages"
        if self._extra_deps_scanning:
            prefix += "  [dim]⏳ checking extras for hidden dependencies…[/]"
        self.query_one("#pkg-title", Label).update(
            f"{prefix}  [dim]OK=installed  !!=missing  ++=extra  "
            f"--=unknown  D=dependency[/]"
        )

    def _split_marked(
        self, action: str, keys: set[str] | None = None
    ) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
        """Split the marked rows into the ones `action` can be applied to
        and the ones it has to skip (with a reason).

        Preconditions per action:
          uninstall         status OK or ++ (i.e. actually installed)
          move / remove     row belongs to a real config (not _extra_)
          uninstall_remove  status exactly OK (installed *and* in a config)

        Rows are returned in table order, not in set order."""
        selected = self._marked if keys is None else keys
        valid: list[tuple[str, str]] = []
        skipped: list[tuple[str, str, str]] = []
        for status, pkg, _tag, key, _is_dep in self._all_rows:
            if key not in selected:
                continue
            config = key.split(":", 1)[0]
            in_config = config != "_extra_"
            installed = status in ("OK", "++")
            if action == "uninstall":
                reason = None if installed else "not installed"
            elif action in ("move", "remove"):
                reason = None if in_config else "not in a config"
            elif action == "uninstall_remove":
                if not installed:
                    reason = "not installed"
                elif not in_config:
                    reason = "not in a config"
                else:
                    reason = None
            else:
                reason = f"unknown action: {action}"
            if reason is None:
                valid.append((config, pkg))
            else:
                skipped.append((config, pkg, reason))
        return valid, skipped

    def _dispatch_action(self, worker_call) -> None:
        """Guard against starting a second config-mutating action
        (_run_pkg_action / _run_bulk_action) while one is still running —
        see _action_busy. worker_call is a zero-arg callable that kicks
        off the (already-decorated, so this returns immediately) worker."""
        if self._action_busy:
            log = self.query_one("#pkg-info", RichLog)
            log.clear()
            log.write(
                Text(
                    "Another package action is still running — wait for it to finish.",
                    style="bold yellow",
                )
            )
            return
        self._action_busy = True
        worker_call()

    def _clear_action_busy(self) -> None:
        self._action_busy = False

    def _start_bulk(self, action: str, keys: set[str] | None = None) -> None:
        """Preview a bulk action and, once confirmed, run it."""
        valid, skipped = self._split_marked(action, keys)
        label = self.BULK_LABELS.get(action, action)
        if not valid:
            log = self.query_one("#pkg-info", RichLog)
            log.clear()
            log.write(
                Text(
                    f"{label}: none of the marked rows is valid for this action.",
                    style="bold yellow",
                )
            )
            for config, pkg, reason in skipped:
                log.write(Text(f"  - {pkg} ({config}): {reason}", style="dim"))
            return
        self.app.push_screen(
            BulkActionConfirmScreen(label, valid, skipped),
            callback=lambda ok: self._on_bulk_confirmed(action, valid, bool(ok)),
        )

    def _on_bulk_confirmed(
        self, action: str, valid: list[tuple[str, str]], confirmed: bool
    ) -> None:
        if not confirmed:
            self._cancel_bulk()
            return
        if action == "move":
            self._show_bulk_dest_picker(valid)
            return
        self._dispatch_action(lambda: self._run_bulk_action(action, valid, None))

    def _cancel_bulk(self) -> None:
        log = self.query_one("#pkg-info", RichLog)
        log.clear()
        log.write(Text("Bulk action cancelled.", style="yellow"))
        self._marked.clear()
        self._redraw_rows()

    def _show_bulk_dest_picker(self, valid: list[tuple[str, str]]) -> None:
        """Ask once where all valid packages should be moved to."""
        sources = {config for config, _ in valid}
        source = next(iter(sources)) if len(sources) == 1 else "marked rows"
        self.app.push_screen(
            DestPickerScreen(
                self._tt_config,
                self._system,
                source,
                f"{len(valid)} marked package(s)",
                True,
                pick_only=True,
            ),
            callback=lambda dest: self._on_bulk_dest_picked(valid, dest),
        )

    def _on_bulk_dest_picked(
        self, valid: list[tuple[str, str]], dest: str | None
    ) -> None:
        if not dest:
            self._cancel_bulk()
            return
        self._dispatch_action(lambda: self._run_bulk_action("move", valid, dest))

    def action_move_package(self) -> None:
        if self._marked:
            self._start_bulk("move")
            return
        result = self._get_selected_key()
        if result:
            self._show_dest_picker(result[0], result[1], move=True)

    def action_copy_package(self) -> None:
        result = self._get_selected_key()
        if result:
            self._show_dest_picker(result[0], result[1], move=False)

    def _show_dest_picker(self, source: str, package: str, move: bool) -> None:
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
        self._dispatch_action(lambda: self._run_pkg_action(pkg, "install"))

    def action_uninstall_package(self) -> None:
        """Uninstall the selected package from the system."""
        if self._marked:
            self._start_bulk("uninstall")
            return
        result = self._get_selected_key()
        if not result:
            return
        _, pkg = result
        self._dispatch_action(lambda: self._run_pkg_action(pkg, "uninstall"))

    def action_uninstall_and_remove(self) -> None:
        """Uninstall the selected/marked packages and, for each one that
        was uninstalled successfully, also drop it from its config."""
        keys = None
        if not self._marked:
            key = self._get_selected_row_key()
            if key is None:
                return
            keys = {key}
        self._start_bulk("uninstall_remove", keys)

    def action_remove_from_config(self) -> None:
        """Remove the selected package from its config file."""
        if self._marked:
            self._start_bulk("remove")
            return
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
        """Add a package to a config. Pre-fills name when an extra (++) package is selected."""
        from tui.screens._add_package import AddPackageScreen
        prefill = ""
        result = self._get_selected_key()
        if result and result[0] == "_extra_":
            prefill = result[1]
        self.app.push_screen(
            AddPackageScreen(self._tt_config, self._system, prefill=prefill),
            callback=self._on_package_added,
        )

    def _on_package_added(self, result: str | None) -> None:
        if result:
            self._refresh_packages()

    def action_toggle_hide_deps(self) -> None:
        self._hide_deps = not self._hide_deps
        self._refresh_packages()

    def _finish_action(self, worker) -> None:
        """Common tail for _run_pkg_action/_run_bulk_action: always clears
        _action_busy, but skips the final refresh (a fresh query_one
        lookup, which raises NoMatches on an unmounted screen) if this
        worker was cancelled — Esc while an action is still running pops
        the screen and cancels its workers' flag, but doesn't stop the
        destructive work already in flight (uninstalling/moving packages
        should finish regardless); only the UI touch afterwards needs
        guarding. Matches the same pattern already used for
        StatusBar._scan_status and _show_package_info."""
        self.app.call_from_thread(self._clear_action_busy)
        if not worker.is_cancelled:
            self.app.call_from_thread(self._refresh_packages)

    @work(thread=True, group="pkg-action")
    def _run_pkg_action(self, package: str, action: str) -> None:
        # group="pkg-action": its own group, distinct from
        # _show_package_info's default-group exclusivity — without this,
        # highlighting a row while an install/uninstall is running would
        # mark this worker cancelled, silently dropping the refresh that
        # shows the result (same class of bug as the "extra-deps" group
        # fix above).
        worker = get_current_worker()
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
            if not success and self._system.installer == "brew":
                # Try to find package in all tapped repos
                self.app.call_from_thread(
                    log.write,
                    Text("Direct install failed, searching taps...", style="yellow"),
                )
                full_name = self._system.search_package_in_taps(package)
                if full_name:
                    self.app.call_from_thread(
                        log.write,
                        Text(f"Found: {full_name}, installing...", style="cyan"),
                    )
                    success, output = self._system.install_package(full_name)
                    if success:
                        # Update config: replace short name with full name
                        # and save the tap
                        tap = full_name.rsplit("/", 1)[0] if "/" in full_name else None
                        if tap:
                            host = self._system.hostname
                            self._tt_config.add_tap(host, tap)
                            self.app.call_from_thread(
                                log.write,
                                Text(f"Saved tap {tap} to config", style="cyan"),
                            )
        else:
            required_by = self._safe_required_by(package)
            if required_by:
                self.app.call_from_thread(
                    log.write,
                    Text(
                        f"Cannot uninstall {package}: required by "
                        f"{', '.join(required_by)}",
                        style="bold red",
                    ),
                )
                self._finish_action(worker)
                return
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
            # After install: check if the package needs a tap and save it
            if action == "install":
                tap = self._system.get_package_tap(package)
                if tap:
                    host = self._system.hostname
                    if self._tt_config.add_tap(host, tap):
                        self.app.call_from_thread(
                            log.write,
                            Text(f"Saved tap {tap} to config", style="cyan"),
                        )
        else:
            self.app.call_from_thread(
                log.write, Text(f"\n{action.title()} failed.", style="bold red")
            )
        # Refresh the table on the main thread
        self._finish_action(worker)

    @work(thread=True, group="pkg-action")
    def _run_bulk_action(
        self, action: str, targets: list[tuple[str, str]], dest: str | None = None
    ) -> None:
        """Apply `action` to every target in turn. A failure on one package
        is logged and does not stop the remaining ones."""
        worker = get_current_worker()
        log = self.query_one("#pkg-info", RichLog)
        label = self.BULK_LABELS.get(action, action)
        self.app.call_from_thread(log.clear)
        self.app.call_from_thread(
            log.write,
            Text(f"{label}: {len(targets)} package(s)", style="bold yellow"),
        )

        done = 0
        failed = 0
        for config, pkg in targets:
            try:
                ok, reason = self._apply_bulk_action(action, config, pkg, dest)
            except Exception as exc:  # never let one package kill the run
                ok, reason = False, str(exc)
            if ok:
                done += 1
                self.app.call_from_thread(log.write, Text(f"✓ {pkg}", style="green"))
            else:
                failed += 1
                self.app.call_from_thread(
                    log.write, Text(f"✗ {pkg}: {reason}", style="red")
                )

        self.app.call_from_thread(log.write, Text(""))
        self.app.call_from_thread(
            log.write,
            Text(
                f"{done} done, {failed} skipped/failed.",
                style="bold green" if not failed else "bold yellow",
            ),
        )
        self.app.call_from_thread(self._marked.clear)
        self._finish_action(worker)
        if not worker.is_cancelled:
            self.app.call_from_thread(self._update_title)

    def _apply_bulk_action(
        self, action: str, config: str, package: str, dest: str | None
    ) -> tuple[bool, str]:
        """Do the actual work for a single package of a bulk action.
        Returns (success, reason-if-not)."""
        installer = self._system.installer
        if action == "remove":
            self._tt_config._remove_package(config, package, installer)
            return True, ""
        if action == "move":
            if not dest or dest == config:
                return False, "no destination config"
            self._tt_config.move_package(config, dest, package, installer)
            return True, ""
        if action in ("uninstall", "uninstall_remove"):
            ok, reason = self._bulk_uninstall(package)
            if not ok:
                if action == "uninstall_remove":
                    return False, f"kept in config, uninstall failed: {reason}"
                return False, reason
            if action == "uninstall_remove":
                self._tt_config._remove_package(config, package, installer)
            return True, ""
        return False, f"unknown action: {action}"

    def _bulk_uninstall(self, package: str) -> tuple[bool, str]:
        """Uninstall one package, using the same reverse-dependency
        pre-check as the single-package action."""
        required_by = self._safe_required_by(package)
        if required_by:
            return False, f"required by {', '.join(required_by)}"
        success, output = self._system.uninstall_package(package)
        if success:
            return True, ""
        detail = next(
            (line.strip() for line in output.splitlines() if line.strip()),
            "uninstall failed",
        )
        return False, detail

    def action_focus_search(self) -> None:
        self.query_one("#pkg-filter", Input).focus()

    def action_switch_pane(self) -> None:
        if self.query_one("#pkg-table", DataTable).has_focus:
            self.query_one("#pkg-info", RichLog).focus()
        else:
            self.query_one("#pkg-table", DataTable).focus()

    def action_page_down(self) -> None:
        """Page the package table down, regardless of which widget
        currently has focus (the filter Input has focus by default and
        doesn't bind pageup/pagedown itself)."""
        self.query_one("#pkg-table", DataTable).action_page_down()

    def action_page_up(self) -> None:
        """Page the package table up, regardless of which widget currently
        has focus."""
        self.query_one("#pkg-table", DataTable).action_page_up()
