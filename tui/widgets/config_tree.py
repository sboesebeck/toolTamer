"""Config hierarchy display widget (read-only)."""

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, Static

from tui.core.config import TTConfig


class ConfigHierarchy(Widget):
    """Displays the config include chain as a static tree diagram."""

    def __init__(self, tt_config: TTConfig, host: str, **kwargs):
        super().__init__(**kwargs)
        self._tt_config = tt_config
        self._host = host

    def compose(self) -> ComposeResult:
        yield Label(
            "[dim]Include chain for this host:[/]",
        )
        yield Static(self._render_tree(), id="hierarchy-text")

    def _render_tree(self) -> str:
        chain = self._tt_config.resolve_chain(self._host)
        lines = []
        for i, cfg in enumerate(chain):
            pkg_count = len(
                self._tt_config.get_packages(cfg, "brew")
            ) + len(
                self._tt_config.get_packages(cfg, "apt")
            )
            file_count = len(self._tt_config.get_file_mappings(cfg))
            indent = "  " * i
            connector = "└─ " if i > 0 else ""
            stats = f"[dim]({pkg_count} pkg, {file_count} files)[/]"

            if cfg == self._host:
                name = f"[bold green]{cfg}[/] ← [dim]this host[/]"
            elif cfg == "common":
                name = f"[cyan]{cfg}[/]"
            else:
                name = f"[blue]{cfg}[/]"

            lines.append(f"{indent}{connector}{name}  {stats}")

        return "\n".join(lines)
