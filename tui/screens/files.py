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
from textual.worker import get_current_worker

from tui.core import repo as repo_mod
from tui.core.config import TTConfig, dir_diff, dir_fully_readable, tree_hash, tree_signature
from tui.core.diff_render import render_changed_diffs
from tui.core.repo import RepoSpec
from tui.core.system import SystemInfo


def _dir_deletions(source: Path, dest: Path) -> list[str]:
    """Return relative paths that exist under dest but not source — i.e., the
    files that would be removed by replacing dest with a fresh copy of source."""
    if not (dest.exists() and dest.is_dir() and source.exists() and source.is_dir()):
        return []
    return dir_diff(source, dest)[1]


# repo_mod.classify() owns the RepoStatus -> bucket mapping (synced/changed/
# missing/broken). These two dicts are display-only, mapping each bucket to
# what this screen already renders for it — a display-status label sharing
# a colour with the plain-file states below, and the list token — so the
# bucket mapping itself is defined exactly once, in tui/core/repo.py.
_BUCKET_TO_STATUS = {
    "synced": "ok",
    "changed": "modified",
    "missing": "missing_system",
    "broken": "missing_repo",
}
_BUCKET_TO_TOKEN = {
    "synced": "OK",
    "changed": "!!",
    "missing": "--",
    "broken": "??",
}


class FileScreen(Screen):
    """View and manage tracked config files."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("a", "apply_to_system", "TT -> System"),
        ("u", "save_change", "Save change"),
        ("r", "remove_from_tt", "Remove"),
        ("m", "move_file", "Move"),
        ("n", "add_file", "Add File"),
        ("g", "convert_to_repo", "To repo"),
        ("slash", "focus_search", "Search"),
        ("tab", "switch_pane", "Switch Pane"),
    ]

    def __init__(self, tt_config: TTConfig, system: SystemInfo):
        super().__init__()
        self._tt_config = tt_config
        self._system = system
        # tree-hash cache: path -> (stat signature, content hash)
        self._tree_cache: dict[str, tuple[str, str]] = {}

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
        log.write(Text("  u  Save change (asks: which content, where)", style="dim"))
        log.write(Text("  r  Remove file from TT config", style="dim"))
        log.write(Text("  m  Move file to another config", style="dim"))
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
            spec = m.repo
            if spec is not None:
                repo_state = repo_mod.status(sys_file, spec)
                status = _BUCKET_TO_STATUS[repo_mod.classify(repo_state)]
            else:
                repo_state = None
                status = self._file_status(m.repo_path, sys_file)

            self_shadow = (not m.is_effective) and m.shadowed_by == m.config
            if not m.is_effective:
                status_token = "==" if self_shadow else "<<"
            elif repo_state is not None:
                status_token = self._repo_status_token(repo_state)
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
            if spec is not None:
                target_text.append(f"  ⎇ {spec.branch or 'HEAD'}", style="dim cyan")
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

    def _cached_tree_hash(self, root: Path) -> str:
        key = str(root)
        sig = tree_signature(root)
        cached = self._tree_cache.get(key)
        if cached and cached[0] == sig:
            return cached[1]
        h = tree_hash(root)
        self._tree_cache[key] = (sig, h)
        return h

    @staticmethod
    def _repo_status_token(state: str) -> str:
        return _BUCKET_TO_TOKEN[repo_mod.classify(state)]

    @staticmethod
    def _repo_detail_lines(spec: RepoSpec, sys_path: Path) -> list[tuple[str, str]]:
        """Detail-pane content for a repo entry: the clone spec plus the
        current local state. No file diff — the store holds no content."""
        lines: list[tuple[str, str]] = [("", "")]
        lines.append(("Tracked as git repository", "bold cyan"))
        lines.append((f"  url    {spec.url or '(missing — .ttgit has no url)'}",
                      "" if spec.url else "bold red"))
        lines.append((f"  branch {spec.branch or '(remote HEAD)'}", ""))
        if spec.force:
            lines.append(("  force  true — local changes are discarded on sync", "yellow"))
        lines.append(("", ""))

        if not spec.url:
            lines.append(("Entry is broken: .ttgit has no url. Sync skips it.", "bold red"))
            return lines

        state = repo_mod.status(sys_path, spec)
        descriptions = {
            "ok": ("Up to date with the remote.", "green"),
            "ahead": ("Local commits not pushed — ToolTamer does not push.", "yellow"),
            "behind": ("Behind the remote — 'a' fast-forwards.", "yellow"),
            "dirty": ("Uncommitted changes — sync skips this repo.", "bold yellow"),
            "diverged": ("Diverged from the remote — sync skips this repo.", "bold yellow"),
            "missing": ("Not cloned yet — 'a' clones it.", "red"),
            "not_a_repo": ("Path exists but is not a git repository root.", "bold red"),
            "wrong_origin": ("origin differs from .ttgit — sync skips this repo.", "bold red"),
            "invalid_spec": (".ttgit has no url.", "bold red"),
        }
        text, style = descriptions.get(state, (f"Unknown state: {state}", "red"))
        lines.append((f"Status: {state} — {text}", style))

        if state in ("missing", "invalid_spec"):
            return lines

        ahead, behind = repo_mod.ahead_behind(sys_path, spec.branch or "HEAD")
        if ahead or behind:
            lines.append((f"  {ahead} ahead / {behind} behind origin", "dim"))
        rc, head = repo_mod._git(["rev-parse", "--short", "HEAD"], cwd=sys_path)
        if rc == 0 and head:
            lines.append((f"  HEAD {head}", "dim"))
        rc, porcelain = repo_mod._git(["status", "--porcelain"], cwd=sys_path)
        if rc == 0 and porcelain:
            lines.append(("", ""))
            lines.append(("Working tree:", "bold"))
            for entry in porcelain.splitlines()[:20]:
                lines.append((f"  {entry}", "dim"))
            extra = len(porcelain.splitlines()) - 20
            if extra > 0:
                lines.append((f"  ... and {extra} more", "dim"))
        return lines

    def _file_status(self, repo: Path, system: Path) -> str:
        if not repo.exists():
            return "missing_repo"
        if not system.exists():
            return "missing_system"
        if repo.is_dir() and system.is_dir():
            try:
                return "ok" if self._cached_tree_hash(repo) == self._cached_tree_hash(system) else "modified"
            except (OSError, PermissionError):
                return "ok"
        if repo.is_dir() or system.is_dir():
            # type mismatch (dir vs file) — needs a sync
            return "modified"
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

    @work(thread=True, exclusive=True)
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

        from tui.core.repo import read_marker
        spec = read_marker(repo_file)
        if spec is not None:
            for text, style in self._repo_detail_lines(spec, sys_file):
                self.app.call_from_thread(log.write, Text(text, style=style))
            return

        if repo_file.is_dir():
            from tui.core.repo import detect as _detect
            hint = _detect(sys_file)
            if hint is not None:
                self.app.call_from_thread(log.write, Text(
                    f"This directory is a git repository ({hint.url}). "
                    f"Press 'g' to track it as a repo instead of copying it.",
                    style="bold yellow",
                ))
                self.app.call_from_thread(log.write, Text(""))

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
                Text(f"Inherited from {config} (u=save a local copy)", style="yellow"),
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
        elif repo_file.is_dir() and sys_file.is_dir():
            only_repo, only_sys, changed = dir_diff(repo_file, sys_file)
            if not (only_repo or only_sys or changed):
                self.app.call_from_thread(log.write, Text("Directories are identical", style="green"))
            else:
                self.app.call_from_thread(
                    log.write,
                    Text(
                        f"Directories differ: {len(only_repo)} only in TT, "
                        f"{len(only_sys)} only on system, {len(changed)} changed",
                        style="yellow",
                    ),
                )
                self.app.call_from_thread(log.write, Text(""))

                if changed:
                    worker = get_current_worker()
                    diff_result = render_changed_diffs(repo_file, sys_file, changed)
                    for cf in diff_result.files:
                        if worker.is_cancelled:
                            return
                        self.app.call_from_thread(
                            log.write, Text(f"~ {cf.rel}  (content differs)", style="yellow")
                        )
                        if cf.diff_lines:
                            for diff_line in cf.diff_lines:
                                line = Text(diff_line)
                                if diff_line.startswith("+"):
                                    line.stylize("green")
                                elif diff_line.startswith("-"):
                                    line.stylize("red")
                                elif diff_line.startswith("@@"):
                                    line.stylize("cyan")
                                self.app.call_from_thread(log.write, line)
                            self.app.call_from_thread(log.write, Text(""))
                        elif cf.binary_line:
                            self.app.call_from_thread(log.write, Text(cf.binary_line, style="dim"))
                            self.app.call_from_thread(log.write, Text(""))
                        elif cf.symlink_line:
                            self.app.call_from_thread(log.write, Text(cf.symlink_line, style="cyan"))
                            self.app.call_from_thread(log.write, Text(""))
                        elif cf.error:
                            self.app.call_from_thread(log.write, Text(cf.error, style="red"))
                            self.app.call_from_thread(log.write, Text(""))

                    if diff_result.diff_unavailable:
                        self.app.call_from_thread(
                            log.write, Text("diff command not available", style="dim")
                        )
                        self.app.call_from_thread(log.write, Text(""))
                    if diff_result.truncated:
                        self.app.call_from_thread(
                            log.write,
                            Text(
                                "(showing inline diffs for the first 10 changed files only)",
                                style="dim",
                            ),
                        )
                        self.app.call_from_thread(log.write, Text(""))

                shown = 0
                for rel in only_repo:
                    if shown >= 60:
                        break
                    self.app.call_from_thread(log.write, Text(f"+ {rel}  (a=apply creates it)", style="green"))
                    shown += 1
                for rel in only_sys:
                    if shown >= 60:
                        break
                    self.app.call_from_thread(log.write, Text(f"x {rel}  (a=apply DELETES it)", style="red"))
                    shown += 1
                total = len(only_repo) + len(only_sys)
                if total > shown:
                    self.app.call_from_thread(log.write, Text(f"... and {total - shown} more", style="dim"))
        elif repo_file.is_dir() or sys_file.is_dir():
            self.app.call_from_thread(
                log.write,
                Text("Type mismatch: one side is a directory, the other a file (a=apply TT version)", style="red"),
            )
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
            Text("a=apply TT->sys  u=save change  r=remove  m=move", style="dim"),
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
        import os
        import shutil
        from tui.core.config import _resolve_effective_target
        from tui.core.repo import read_marker, sync_to_system
        repo_file = self._tt_config.configs_dir / config / "files" / stored
        sys_file = Path.home() / _resolve_effective_target(stored, target)
        if not repo_file.exists():
            return
        if repo_file.is_dir() and not os.access(repo_file, os.R_OK | os.X_OK):
            # R28: an unreadable store directory tells us nothing about what
            # it holds. It may in fact be a repo entry whose .ttgit we simply
            # cannot see — read_marker below stats a path *inside* repo_file,
            # which needs search permission on repo_file itself, so on this
            # Python/OS it raises PermissionError rather than politely
            # reporting "no marker" (verified directly, not assumed — see
            # the task report). Checked here, before read_marker is even
            # called: sys_file is a normal, fully readable path, so
            # shutil.rmtree(sys_file) below would succeed outright — deleting
            # a possibly-real repository — before shutil.copytree(repo_file,
            # ...) got anywhere near failing on the unreadable source. The
            # guard belongs at this destructive step, not at the detector:
            # no read_marker predicate can distinguish "empty directory" from
            # "repo entry" when it cannot see inside repo_file at all.
            self.notify(
                f"Cannot read {repo_file} — store entry unreadable, skipped",
                severity="error", timeout=8,
            )
            return
        spec = read_marker(repo_file)
        if spec is not None:
            # A repo entry is synced with clone/pull, never mirrored via
            # rmtree+copytree — that would destroy the user's real repo
            # (and any uncommitted work in it) below.
            result = sync_to_system(sys_file, spec)
            severity = {"failed": "error", "skipped": "warning"}.get(result.action, "information")
            self.notify(result.message, severity=severity, timeout=8)
            self._refresh_files()
            self._show_diff(config, stored, target)
            return
        if repo_file.is_dir() and not dir_fully_readable(repo_file):
            # C1: the os.access() check above only sees the top level. A store
            # dir that is readable there but holds an unreadable subdirectory
            # gets past it, and then rmtree(sys_file) succeeds before
            # copytree() raises shutil.Error on the subtree it cannot read —
            # the system side is left half-deleted. bin/include.sh puts the
            # same guard in mirrorDir, i.e. on the mirror path only; repo
            # entries return above and never reach it, exactly as they never
            # reach mirrorDir.
            self.notify(
                f"Cannot fully read {repo_file} — unreadable subdirectory, skipped",
                severity="error", timeout=8,
            )
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

    def _save_repo_marker(self, config: str, stored: str, target: str) -> str:
        """System -> TT for a repo entry: refresh url/branch in .ttgit.

        Never captures content and never removes the marker."""
        from tui.core.config import _resolve_effective_target
        from tui.core.repo import current_branch, origin_url, read_marker, repo_root, write_marker

        store = self._tt_config.configs_dir / config / "files" / stored
        eff = _resolve_effective_target(stored, target)
        sys_path = Path.home() / eff
        current = read_marker(store)
        if current is None:
            return "Not a repo entry."
        # I1: "not a repo root" and "no origin remote" are separate answers,
        # as they are in captureRepoFromSystem. Collapsing them told the user
        # a live repository was not a repository, which they cannot act on.
        if repo_root(sys_path) is None:
            return f"~/{eff} is not a git repository root — marker unchanged."
        found_url = origin_url(sys_path)
        if found_url is None:
            return (
                f"~/{eff} has no 'origin' remote — marker unchanged. "
                f"ToolTamer records origin; add one or rename the remote back."
            )
        found_branch = current_branch(sys_path)
        if found_url == current.url and found_branch == current.branch:
            return "Marker already matches the system — nothing to save."
        write_marker(store, RepoSpec(url=found_url, branch=found_branch, force=current.force))
        return (
            f"Updated .ttgit: url {found_url}"
            + (f", branch {found_branch}" if found_branch else "")
        )

    def action_save_change(self) -> None:
        """Unified save (merges the old 'capture' and 'override local').

        For host-local entries there is only one sensible target, so the
        current system state is captured directly. For inherited entries the
        user is asked what content to store (current system state vs. the
        inherited copy) and where (the shared parent config vs. a host-local
        override)."""
        sel = self._get_selected()
        if not sel:
            return
        config, stored, target = sel
        from tui.core.config import _resolve_effective_target
        eff_target = _resolve_effective_target(stored, target)
        sys_file = Path.home() / eff_target
        repo_file = self._tt_config.configs_dir / config / "files" / stored
        host = self._system.hostname

        from tui.core.repo import read_marker as _read_marker
        if _read_marker(repo_file) is not None:
            log = self.query_one("#file-diff", RichLog)
            log.clear()
            log.write(Text(self._save_repo_marker(config, stored, target), style="cyan"))
            self._refresh_files()
            return

        if config == host:
            # Already host-local: nothing to choose, just capture the system state.
            if not sys_file.exists():
                log = self.query_one("#file-diff", RichLog)
                log.clear()
                log.write(Text("Nothing on the system to capture.", style="yellow"))
                return
            self._capture_with_check(config, stored, target, "parent")
            return

        if not sys_file.exists() and not repo_file.exists():
            log = self.query_one("#file-diff", RichLog)
            log.clear()
            log.write(Text("Neither system nor repo copy exists — nothing to save.", style="yellow"))
            return

        self.app.push_screen(
            SaveChoiceScreen(
                config, host, eff_target,
                system_exists=sys_file.exists(),
                repo_exists=repo_file.exists(),
            ),
            callback=lambda choice: self._handle_save_choice(config, stored, target, choice),
        )

    def _handle_save_choice(self, config: str, stored: str, target: str, choice: str | None) -> None:
        if choice == "system_parent":
            self._capture_with_check(config, stored, target, "parent")
        elif choice == "system_override":
            self._capture_with_check(config, stored, target, "override")
        elif choice == "repo_override":
            self._override_from_repo(config, stored, target)

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
        if sys_path.is_dir() and not dir_fully_readable(sys_path):
            # C1, capture direction: the store is the one that gets rmtree'd
            # here, so an unreadable subtree on the system side would empty
            # the stored copy and then fail. Same refusal as mirrorDir.
            self.notify(
                f"Cannot fully read {sys_path} — unreadable subdirectory, "
                f"stored copy left untouched",
                severity="error", timeout=8,
            )
            return
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
        deleted = self._tt_config.remove_file(config, stored, target)
        log = self.query_one("#file-diff", RichLog)
        log.clear()
        log.write(Text(f"Removed ~/{eff_target} from {config}", style="green"))
        log.write(Text("File remains on system, just no longer managed by TT.", style="dim"))
        if deleted:
            log.write(Text("Stored copy deleted from the TT config.", style="dim"))
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

    def _override_from_repo(self, config: str, stored: str, target: str) -> None:
        """Copy an inherited file/dir from its parent config into the host
        config, so it can be edited locally. Confirms directory deletions
        first, mirroring _capture_with_check."""
        host = self._system.hostname
        src_path = self._tt_config.configs_dir / config / "files" / stored
        if not src_path.exists():
            return
        dest_path = self._tt_config.configs_dir / host / "files" / stored
        if src_path.is_dir() and dest_path.is_dir():
            deletions = _dir_deletions(src_path, dest_path)
            if deletions:
                from tui.core.config import _resolve_effective_target
                eff_target = _resolve_effective_target(stored, target)
                self.app.push_screen(
                    ConfirmDeletionsScreen(
                        f"Copy '{config}' → local override of ~/{eff_target}",
                        deletions,
                        "delete and copy",
                    ),
                    callback=lambda ok: self._do_override_from_repo(config, stored, target) if ok else None,
                )
                return
        self._do_override_from_repo(config, stored, target)

    def _do_override_from_repo(self, config: str, stored: str, target: str) -> None:
        import shutil

        host = self._system.hostname
        src_path = self._tt_config.configs_dir / config / "files" / stored
        if not src_path.exists():
            return
        dest_path = self._tt_config.configs_dir / host / "files" / stored
        if src_path.is_dir() and not dir_fully_readable(src_path):
            # C1, store-to-store direction: the host config's copy is the
            # victim of the rmtree below.
            self.notify(
                f"Cannot fully read {src_path} — unreadable subdirectory, "
                f"local override left untouched",
                severity="error", timeout=8,
            )
            return
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if src_path.is_dir():
            if dest_path.exists():
                if dest_path.is_dir():
                    shutil.rmtree(dest_path)
                else:
                    dest_path.unlink()
            shutil.copytree(src_path, dest_path)
        else:
            dest_path.write_bytes(src_path.read_bytes())
        self._tt_config.add_file_mapping(host, stored, target)
        from tui.core.config import _resolve_effective_target
        eff_target = _resolve_effective_target(stored, target)
        log = self.query_one("#file-diff", RichLog)
        log.clear()
        log.write(Text(f"Copied ~/{eff_target} to {host} config", style="green"))
        log.write(Text(f"Was inherited from {config}, now local.", style="dim"))
        log.write(Text("Edit the local copy, then u=save change.", style="dim"))
        self._refresh_files()

    def action_add_file(self) -> None:
        """Add a new file or directory to TT. Uses fzf when available."""
        import shutil as _sh

        if _sh.which("fzf"):
            picked = self._pick_with_fzf()
            if picked is None:
                return
            self._continue_add(picked)
        else:
            self.app.push_screen(AddFileScreen(self._tt_config, self._system))

    def _continue_add(self, picked: Path) -> None:
        """Ask about repo tracking when `picked` is a repo root, then pick
        the target config."""
        spec = repo_mod.detect(picked)
        if spec is None:
            self.app.push_screen(
                AddConfigPickScreen(self._tt_config, self._system, picked),
                callback=lambda _: self._refresh_files(),
            )
            return

        def _after(choice: str | None) -> None:
            if choice is None:
                return
            self.app.push_screen(
                AddConfigPickScreen(
                    self._tt_config, self._system, picked,
                    as_repo=(choice == "repo"),
                    repo_spec=spec if choice == "repo" else None,
                ),
                callback=lambda _: self._refresh_files(),
            )

        self.app.push_screen(RepoTrackChoiceScreen(picked, spec), callback=_after)

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

    def _convertible(self, config: str, stored: str, target: str) -> RepoSpec | None:
        """The RepoSpec for a tracked *directory* entry whose system side is
        a git repo root and which is not already a repo entry. Else None."""
        from tui.core.config import _resolve_effective_target

        store = self._tt_config.configs_dir / config / "files" / stored
        if repo_mod.read_marker(store) is not None:
            return None
        if not store.is_dir():
            return None
        sys_path = Path.home() / _resolve_effective_target(stored, target)
        return repo_mod.detect(sys_path)

    def _convert_blocked_reason(self, config: str, stored: str, target: str) -> str:
        """Why `g` cannot convert this entry — one sentence the user can act on.

        I1 knock-on: this used to be a single catch-all ("Only tracked
        directories whose system path is a git repo root can be converted"),
        which is plainly false for a directory that IS a repo root and merely
        lacks an origin remote."""
        from tui.core.config import _resolve_effective_target

        store = self._tt_config.configs_dir / config / "files" / stored
        eff = _resolve_effective_target(stored, target)
        if repo_mod.read_marker(store) is not None:
            return f"~/{eff} is already tracked as a git repo entry."
        if not store.is_dir():
            return f"~/{eff} is not a tracked directory — only directories can be converted."
        sys_path = Path.home() / eff
        if repo_mod.repo_root(sys_path) is None:
            return f"~/{eff} is not a git repository root — nothing to convert it to."
        if repo_mod.origin_url(sys_path) is None:
            return (
                f"~/{eff} is a git repository but has no 'origin' remote — "
                f"ToolTamer needs one to record in .ttgit."
            )
        return f"~/{eff} cannot be converted."

    def action_convert_to_repo(self) -> None:
        sel = self._get_selected()
        if not sel:
            return
        config, stored, target = sel
        spec = self._convertible(config, stored, target)
        if spec is None:
            self.notify(
                self._convert_blocked_reason(config, stored, target),
                severity="warning", timeout=6,
            )
            return
        store = self._tt_config.configs_dir / config / "files" / stored
        from tui.core.config import _resolve_effective_target, iter_tree_files
        count = sum(1 for _ in iter_tree_files(store))
        eff = _resolve_effective_target(stored, target)

        def _after(confirmed: bool | None) -> None:
            if not confirmed:
                return
            report = self._tt_config.convert_to_repo(config, stored, spec)
            for line in report:
                self.notify(line, timeout=8)
            self._tree_cache.clear()
            self._refresh_files()
            self._show_diff(config, stored, target)

        self.app.push_screen(
            ConvertToRepoScreen(eff, config, spec, count), callback=_after
        )


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


class ConvertToRepoScreen(ModalScreen[bool]):
    """Confirm turning a tracked directory into a git-repo entry."""

    BINDINGS = [("escape", "cancel", "Cancel"), ("y", "confirm", "Convert")]

    DEFAULT_CSS = """
    ConvertToRepoScreen {
        align: center middle;
    }
    #convert-repo-dialog {
        width: 76;
        height: auto;
        border: round $warning;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, eff_target: str, config: str, spec: RepoSpec, file_count: int):
        super().__init__()
        self._eff_target = eff_target
        self._config = config
        self._spec = spec
        self._file_count = file_count

    def compose(self) -> ComposeResult:
        with Container(id="convert-repo-dialog"):
            yield Label(Text.assemble(
                ("Convert ", "bold"), (f"~/{self._eff_target}", "cyan"),
                (f" in '{self._config}' to a repo entry", "bold"),
            ))
            yield Label(Text(""))
            yield Label(Text(f"  origin  {self._spec.url}", style="dim"))
            yield Label(Text(f"  branch  {self._spec.branch or '(remote HEAD)'}", style="dim"))
            yield Label(Text(""))
            yield Label(Text(
                f"{self._file_count} stored file(s) will be removed from ToolTamer.",
                style="bold yellow",
            ))
            yield Label(Text(
                "Your system copy is not touched. ToolTamer will sync it with "
                "clone/pull from now on.", style="dim",
            ))
            yield Label(Text(""))
            yield Label(Text("y=convert  Esc=cancel", style="dim"))

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class RepoTrackChoiceScreen(ModalScreen[str | None]):
    """Asked when the path being added is a git repository root: track the
    clone spec, or copy the contents like any other directory."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("r", "pick_repo", "Track as repo"),
        ("c", "pick_copy", "Copy contents"),
    ]

    DEFAULT_CSS = """
    RepoTrackChoiceScreen {
        align: center middle;
    }
    #repo-choice-dialog {
        width: 76;
        height: auto;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, source: Path, spec: RepoSpec):
        super().__init__()
        self._source = source
        self._spec = spec

    def compose(self) -> ComposeResult:
        rel = str(self._source.relative_to(Path.home()))
        with Container(id="repo-choice-dialog"):
            yield Label(Text.assemble(
                ("~/", "cyan"), (rel, "bold cyan"), (" is a git repository", ""),
            ))
            yield Label(Text(""))
            yield Label(Text(f"  origin  {self._spec.url}", style="dim"))
            yield Label(Text(f"  branch  {self._spec.branch or '(remote HEAD)'}", style="dim"))
            yield Label(Text(""))
            yield OptionList(
                Option("Track as repo — store url/branch, sync with clone/pull", id="repo"),
                Option("Copy contents — mirror every file into ToolTamer", id="copy"),
            )
            yield Label(Text(""))
            yield Label(Text("r=repo  c=copy  Esc=cancel", style="dim"))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.id))

    def action_pick_repo(self) -> None:
        self.dismiss("repo")

    def action_pick_copy(self) -> None:
        self.dismiss("copy")

    def action_cancel(self) -> None:
        self.dismiss(None)


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

    def __init__(
        self, tt_config: TTConfig, system: SystemInfo, source: Path,
        as_repo: bool = False, repo_spec: RepoSpec | None = None,
    ):
        super().__init__()
        self._tt_config = tt_config
        self._system = system
        self._source = source
        self._as_repo = as_repo
        self._repo_spec = repo_spec

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

    def _add_to(self, dest: str) -> list[str]:
        """Perform the add for the target config `dest`. Split out from the
        event handler so it is testable without a running app."""
        return self._tt_config.add_path(
            dest, self._source, self._system.hostname,
            as_repo=self._as_repo, repo_spec=self._repo_spec,
        )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        dest = str(event.option.id)
        report = self._add_to(dest)
        for line in report[:8]:
            severity = "warning" if line.startswith("WARNING") else "information"
            if line.startswith("ERROR"):
                severity = "error"
            self.app.notify(line, severity=severity, timeout=8)
        if len(report) > 8:
            self.app.notify(f"... and {len(report) - 8} more changes", timeout=8)
        self.dismiss(dest)

    def action_cancel(self) -> None:
        self.dismiss(None)


class SaveChoiceScreen(ModalScreen[str | None]):
    """Unified chooser for saving a change on an inherited file: pick what
    content to store (current system state vs. the inherited copy) and where
    (the shared parent config vs. a host-local override). Merges the old
    'capture' (u) and 'override local' (o) actions."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("a", "pick('system_parent')", "All hosts"),
        ("l", "pick('system_override')", "Local"),
        ("c", "pick('repo_override')", "Copy parent"),
    ]

    DEFAULT_CSS = """
    SaveChoiceScreen {
        align: center middle;
    }
    #save-choice-dialog {
        width: 78;
        height: auto;
        max-height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(
        self,
        parent_config: str,
        host: str,
        eff_target: str,
        system_exists: bool,
        repo_exists: bool,
    ):
        super().__init__()
        self._parent_config = parent_config
        self._host = host
        self._eff_target = eff_target
        self._system_exists = system_exists
        self._repo_exists = repo_exists

    def compose(self) -> ComposeResult:
        with Container(id="save-choice-dialog"):
            yield Label(Text.assemble(
                ("Save ", "bold"),
                (f"~/{self._eff_target}", "cyan"),
                (" — inherited from ", ""),
                (self._parent_config, "yellow"),
                (".", ""),
            ))
            yield Label(Text(""))
            yield Label(Text("What should be saved, and where?", style="bold"))
            yield Label(Text(""))
            # Plain Text prompts: "[a]"/"[l]"/"[c]" would be parsed as Rich
            # markup style tags ("c" means conceal — invisible options).
            options = []
            if self._system_exists:
                options.append(Option(
                    Text.assemble(
                        ("[a]", "bold yellow"),
                        (f" Current system state → '{self._parent_config}' (affects all hosts)", ""),
                    ),
                    id="system_parent",
                ))
                options.append(Option(
                    Text.assemble(
                        ("[l]", "bold yellow"),
                        (f" Current system state → LOCAL override (only {self._host})", ""),
                    ),
                    id="system_override",
                ))
            if self._repo_exists:
                options.append(Option(
                    Text.assemble(
                        ("[c]", "bold yellow"),
                        (f" Copy '{self._parent_config}' version → LOCAL override to edit (only {self._host})", ""),
                    ),
                    id="repo_override",
                ))
            yield OptionList(*options)
            yield Label(Text(""))
            yield Label(Text("Esc=cancel  a=all hosts  l=local  c=copy parent", style="dim"))

    def _valid(self, choice: str) -> bool:
        if choice in ("system_parent", "system_override"):
            return self._system_exists
        if choice == "repo_override":
            return self._repo_exists
        return False

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.id))

    def action_pick(self, choice: str) -> None:
        if self._valid(choice):
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
        if self._selected_path is None:
            return
        sys_path = self._selected_path
        if not sys_path.exists():
            return
        try:
            sys_path.relative_to(Path.home())
        except ValueError:
            return

        dest = str(event.option.id)
        spec = repo_mod.detect(sys_path)
        if spec is None:
            self._finish_add(dest)
            return

        def _after(choice: str | None) -> None:
            if choice is None:
                return
            self._finish_add(
                dest, as_repo=(choice == "repo"),
                repo_spec=spec if choice == "repo" else None,
            )

        self.app.push_screen(RepoTrackChoiceScreen(sys_path, spec), callback=_after)

    def _add_selected(
        self, dest: str, as_repo: bool = False, repo_spec: RepoSpec | None = None,
    ) -> list[str]:
        """Add the currently selected path to `dest`. Split out from
        `_finish_add` so it is testable without a running app."""
        return self._tt_config.add_path(
            dest, self._selected_path, self._system.hostname,
            as_repo=as_repo, repo_spec=repo_spec,
        )

    def _finish_add(
        self, dest: str, as_repo: bool = False, repo_spec: RepoSpec | None = None,
    ) -> None:
        report = self._add_selected(dest, as_repo=as_repo, repo_spec=repo_spec)
        for line in report[:8]:
            severity = "warning" if line.startswith("WARNING") else "information"
            self.app.notify(line, severity=severity, timeout=8)
        if len(report) > 8:
            self.app.notify(f"... and {len(report) - 8} more changes", timeout=8)
        self.app.pop_screen()

    def action_go_back(self) -> None:
        self.app.pop_screen()
