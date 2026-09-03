"""Status summary widget for the dashboard."""

import hashlib
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Label
from textual.worker import get_current_worker

from tui.core import repo as repo_mod
from tui.core.config import TTConfig, tree_hash
from tui.core.dep_cache import DependencyResolver, default_cache_path
from tui.core.pkg_names import installed_index, is_installed, short_name
from tui.core.system import SystemInfo


class StatusBar(Widget):
    """Shows host, OS, installer, and live change details."""

    def __init__(
        self,
        tt_config: TTConfig,
        system: SystemInfo,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._tt_config = tt_config
        self._system = system
        # Same on-disk cache the package screen and tt-cleanup-deps use.
        self._deps = DependencyResolver(
            system, default_cache_path(tt_config.base)
        )

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("Host    ", classes="label-key")
            yield Label(self._system.hostname, classes="label-value", id="host-value")
        with Horizontal():
            yield Label("OS      ", classes="label-key")
            yield Label(
                f"{self._system.os_type} ({self._system.installer})",
                classes="label-value",
            )
        with Horizontal():
            yield Label("Configs ", classes="label-key")
            chain = self._tt_config.resolve_chain(self._system.hostname)
            yield Label(
                " → ".join(chain),
                classes="label-value",
            )
        with Horizontal():
            yield Label("Pkgs    ", classes="label-key")
            yield Label("[dim]scanning...[/]", classes="label-value", id="pkg-count")
        yield Label("", id="pkg-details")
        with Horizontal():
            yield Label("Files   ", classes="label-key")
            yield Label("[dim]scanning...[/]", classes="label-value", id="file-count")
        yield Label("", id="file-details")

    def on_mount(self) -> None:
        self._scan_status()

    def refresh_status(self) -> None:
        """Re-run the status scan (call after returning from sub-screens)."""
        self._scan_status()

    @staticmethod
    def _format_pkg_summary(
        total_pkgs: int,
        missing_pkgs: list[str],
        excess_pkgs: list[str],
        refining: bool = False,
    ) -> tuple[str, str]:
        """Build the (summary, detail) text pair for #pkg-count /
        #pkg-details. Shared between the fast pass (cheap install-reason
        signal) and the refined pass (structural check) below, so both
        render identically apart from the excess list itself and the
        "refining" suffix."""
        pkg_text = f"{total_pkgs} managed"
        if missing_pkgs:
            pkg_text += f", [red]{len(missing_pkgs)} missing[/]"
        if excess_pkgs:
            pkg_text += f", [yellow]{len(excess_pkgs)} extra[/]"
        if not missing_pkgs and not excess_pkgs:
            pkg_text += " [green]— all synced[/]"
        if refining:
            pkg_text += "  [dim]⏳ refining...[/]"

        pkg_detail_parts = []
        if missing_pkgs:
            names = ", ".join(missing_pkgs[:10])
            if len(missing_pkgs) > 10:
                names += f" +{len(missing_pkgs) - 10} more"
            pkg_detail_parts.append(f"[red]Missing:[/] {names}")
        if excess_pkgs:
            names = ", ".join(excess_pkgs[:10])
            if len(excess_pkgs) > 10:
                names += f" +{len(excess_pkgs) - 10} more"
            pkg_detail_parts.append(f"[yellow]Extra:[/] {names}")
        pkg_details = " | ".join(pkg_detail_parts) if pkg_detail_parts else ""
        return pkg_text, pkg_details

    def _refine_excess_pkgs(
        self, excess_pkgs: list[str], installed: list[str], should_stop=None
    ) -> list[str]:
        """The cheap list_dependency_packages() signal used for the fast
        pass can miss real dependencies (the json-glib report) — this
        re-checks each excess/"extra" package with the same structural
        get_required_by() check the package screen uses. Returns the
        subset of excess_pkgs still genuinely unaccounted for once that's
        in. Shares the on-disk cache (and its parallel cold-cache path)
        with the package screen and tt-cleanup-deps, so on a warm cache
        this costs nothing and the dashboard number is exact."""
        if not excess_pkgs:
            return []
        resolved = self._deps.resolve(
            excess_pkgs, installed=installed, should_stop=should_stop
        )
        return sorted(p for p in excess_pkgs if not resolved.get(p))

    @work(thread=True, exclusive=True)
    def _scan_status(self) -> None:
        worker = get_current_worker()
        host = self._system.hostname
        installer = self._system.installer

        # Package scan — fast pass first (cheap install-reason signal),
        # refined in the background further down, after the file scan is
        # already shown, with the same structural check the package
        # screen uses (see _refine_excess_pkgs).
        effective = self._tt_config.get_effective_packages(host, installer)
        effective_set = set(effective)
        total_pkgs = len(effective)
        missing_pkgs: list[str] = []
        excess_pkgs: list[str] = []
        installed_list: list[str] = []
        try:
            installed_list = self._system.list_installed_packages()
            installed = set(installed_list)
            try:
                dep_only = set(self._system.list_dependency_packages())
            except Exception:
                dep_only = set()
            # Configs may name tap packages fully qualified
            # (forketyfork/tap/clawtunes) while the package manager lists
            # them short (clawtunes) — compare across both forms, or every
            # tap package shows up as both "missing" and "extra".
            installed_idx = installed_index(installed)
            effective_short = {short_name(p) for p in effective_set}
            missing_pkgs = sorted(
                p for p in effective if not is_installed(p, installed_idx)
            )
            excess_pkgs = sorted(
                p for p in installed
                if short_name(p) not in effective_short and p not in dep_only
            )
            pkg_text, pkg_details = self._format_pkg_summary(
                total_pkgs, missing_pkgs, excess_pkgs, refining=bool(excess_pkgs)
            )
        except Exception:
            pkg_text = f"{total_pkgs} managed"
            pkg_details = ""

        if worker.is_cancelled:
            return
        self.app.call_from_thread(
            self.query_one("#pkg-count", Label).update, pkg_text
        )
        self.app.call_from_thread(
            self.query_one("#pkg-details", Label).update, pkg_details
        )

        # File scan — only count the effective (winning) mapping per target,
        # so duplicates inherited from parent configs aren't double-counted.
        mappings = [
            m for m in self._tt_config.get_effective_file_mappings(host)
            if m.is_effective
        ]
        total_files = len(mappings)
        modified_files: list[str] = []
        missing_file_names: list[str] = []
        broken_repos: list[str] = []
        home = Path.home()
        for m in mappings:
            sys_file = home / m.effective_target
            spec = m.repo
            if spec is not None:
                # A repo entry's store side holds only a .ttgit marker, so
                # comparing tree hashes here (as for a plain file/dir entry)
                # would always find them different and report every repo
                # entry as "changed" forever. fetch=False (the default) is
                # required: this scan runs on a timer, inside a worker, and
                # must stay offline.
                bucket = repo_mod.classify(repo_mod.status(sys_file, spec))
                if bucket == "changed":
                    modified_files.append(m.effective_target)
                elif bucket == "missing":
                    missing_file_names.append(m.effective_target)
                elif bucket == "broken":
                    broken_repos.append(m.effective_target)
                continue
            if not m.repo_path.exists() or not sys_file.exists():
                missing_file_names.append(m.effective_target)
            elif sys_file.is_dir() and m.repo_path.is_dir():
                try:
                    if tree_hash(m.repo_path) != tree_hash(sys_file):
                        modified_files.append(m.effective_target)
                except (OSError, PermissionError):
                    continue
            elif sys_file.is_dir() or m.repo_path.is_dir():
                # type mismatch counts as changed
                modified_files.append(m.effective_target)
            else:
                try:
                    if hashlib.sha1(m.repo_path.read_bytes()).hexdigest() != hashlib.sha1(sys_file.read_bytes()).hexdigest():
                        modified_files.append(m.effective_target)
                except (OSError, PermissionError):
                    continue

        file_text = f"{total_files} managed"
        if modified_files:
            file_text += f", [yellow]{len(modified_files)} changed[/]"
        if missing_file_names:
            file_text += f", [red]{len(missing_file_names)} missing[/]"
        if broken_repos:
            file_text += f", [red]{len(broken_repos)} broken[/]"
        if not modified_files and not missing_file_names and not broken_repos:
            file_text += " [green]— all synced[/]"

        file_detail_parts = []
        if modified_files:
            names = ", ".join(modified_files[:5])
            if len(modified_files) > 5:
                names += f" +{len(modified_files) - 5} more"
            file_detail_parts.append(f"[yellow]Changed:[/] {names}")
        if missing_file_names:
            names = ", ".join(missing_file_names[:5])
            if len(missing_file_names) > 5:
                names += f" +{len(missing_file_names) - 5} more"
            file_detail_parts.append(f"[red]Missing:[/] {names}")
        if broken_repos:
            names = ", ".join(broken_repos[:5])
            if len(broken_repos) > 5:
                names += f" +{len(broken_repos) - 5} more"
            file_detail_parts.append(f"[red]Broken repo:[/] {names}")
        file_details = " | ".join(file_detail_parts) if file_detail_parts else ""

        if worker.is_cancelled:
            return
        self.app.call_from_thread(
            self.query_one("#file-count", Label).update, file_text
        )
        self.app.call_from_thread(
            self.query_one("#file-details", Label).update, file_details
        )

        # Refine the "extra" package count now that the fast numbers are
        # already on screen — see _refine_excess_pkgs.
        if excess_pkgs:
            refined_excess = self._refine_excess_pkgs(
                excess_pkgs,
                installed=installed_list,
                should_stop=lambda: worker.is_cancelled,
            )
            if worker.is_cancelled:
                return
            pkg_text, pkg_details = self._format_pkg_summary(
                total_pkgs, missing_pkgs, refined_excess
            )
            self.app.call_from_thread(
                self.query_one("#pkg-count", Label).update, pkg_text
            )
            self.app.call_from_thread(
                self.query_one("#pkg-details", Label).update, pkg_details
            )
