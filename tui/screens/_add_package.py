"""Modal screen to add a new package to a config."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from tui.core.config import TTConfig
from tui.core.system import SystemInfo


class AddPackageScreen(ModalScreen[str | None]):
    """Modal to add a new package name to a chosen config."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    AddPackageScreen {
        align: center middle;
    }
    #add-pkg-dialog {
        width: 50;
        height: auto;
        max-height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #add-pkg-dialog Input {
        margin: 1 0;
    }
    """

    def __init__(self, tt_config: TTConfig, system: SystemInfo, prefill: str = ""):
        super().__init__()
        self._tt_config = tt_config
        self._system = system
        self._prefill = prefill

    def compose(self) -> ComposeResult:
        with Container(id="add-pkg-dialog"):
            if self._prefill:
                yield Label(f"[bold]Add [cyan]{self._prefill}[/cyan] to config[/]")
                yield Input(value=self._prefill, id="pkg-name-input", disabled=True)
            else:
                yield Label("[bold]Add package to config[/]")
                yield Input(placeholder="Package name", id="pkg-name-input")
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
        pkg = self.query_one("#pkg-name-input", Input).value.strip()
        if not pkg:
            return
        dest = str(event.option.id)
        self._tt_config._add_package(dest, pkg, self._system.installer)
        self.dismiss(pkg)

    def action_cancel(self) -> None:
        self.dismiss(None)
