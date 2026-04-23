"""Destination config picker for package move/copy."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from tui.core.config import TTConfig
from tui.core.system import SystemInfo


class DestPickerScreen(ModalScreen[str | None]):
    """Modal screen to pick a destination config for move/copy."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    DestPickerScreen {
        align: center middle;
    }
    #dest-dialog {
        width: 50;
        height: auto;
        max-height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, tt_config: TTConfig, system: SystemInfo, source_config: str, package: str, is_move: bool):
        super().__init__()
        self._tt_config = tt_config
        self._system = system
        self._source = source_config
        self._package = package
        self._is_move = is_move

    def compose(self) -> ComposeResult:
        action = "Move" if self._is_move else "Copy"
        with Container(id="dest-dialog"):
            yield Label(f"[bold]{action}[/] [cyan]{self._package}[/] from [yellow]{self._source}[/] to:")
            yield Label("")
            options = []
            parents = self._tt_config.get_parents(self._system.hostname)
            children = self._tt_config.get_children(self._source)
            for cfg in self._tt_config.list_configs():
                if cfg == self._source:
                    continue
                tag = ""
                if cfg in parents:
                    tag = " [cyan][parent][/]"
                elif cfg in children:
                    tag = " [blue][child][/]"
                elif cfg == self._system.hostname:
                    tag = " [green][host][/]"
                elif cfg == "common":
                    tag = " [cyan][common][/]"
                existing = self._tt_config.get_packages(cfg, self._system.installer)
                if self._package in existing:
                    tag += " [dim](has pkg)[/]"
                options.append(Option(f"{cfg}{tag}", id=cfg))
            yield OptionList(*options, id="dest-list")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        dest = str(event.option.id)
        if self._is_move:
            self._tt_config.move_package(self._source, dest, self._package, self._system.installer)
        else:
            self._tt_config.copy_package(self._source, dest, self._package, self._system.installer)
        self.dismiss(dest)

    def action_cancel(self) -> None:
        self.dismiss(None)
