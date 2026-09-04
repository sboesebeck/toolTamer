"""Modal to set this machine's id — the name of the host config it uses.

The id defaults to the hostname but need not be one; anything that works
as a directory name under configs/ is fine. The dialog only collects the
name; DashboardScreen applies it (rename + write + redraw).
"""

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class MachineIdScreen(ModalScreen[str | None]):
    """Dismisses with the new id, or None when cancelled/unchanged."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    MachineIdScreen {
        align: center middle;
    }
    #machine-id-dialog {
        width: 70;
        height: auto;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #machine-id-dialog Input {
        margin: 1 0;
    }
    """

    def __init__(
        self,
        current: str,
        real_hostname: str,
        configs: list[str],
        includers: list[str] = (),
    ):
        super().__init__()
        self._current = current
        self._real_hostname = real_hostname
        self._configs = configs
        # Configs whose includes.conf names `current`; rename_config will
        # repoint them, and that is worth saying before Enter.
        self._includers = list(includers)

    def compose(self) -> ComposeResult:
        with Container(id="machine-id-dialog"):
            yield Label("[bold]Machine id[/]")
            yield Label(
                "[dim]Names the host config this machine uses. "
                f"Hostname right now: [/]{self._real_hostname}"
            )
            yield Input(value=self._current, id="machine-id-input")
            yield Label(self._hint(self._current), id="machine-id-hint")

    def _hint(self, value: str) -> str:
        value = value.strip()
        if not value or value == self._current:
            return "[dim]Enter: keep as is · Esc: cancel[/]"
        if value in self._configs:
            return f"[dim]Enter: switch to existing config [/][cyan]{value}[/]"
        if self._current in self._configs:
            hint = (
                f"[dim]Enter: rename config [/][cyan]{self._current}[/]"
                f"[dim] → [/][cyan]{value}[/]"
            )
            if self._includers:
                hint += f"[dim], also updates includes in: {', '.join(self._includers)}[/]"
            return hint
        return f"[dim]Enter: use [/][cyan]{value}[/][dim] (config created on next tt run)[/]"

    def on_input_changed(self, event: Input.Changed) -> None:
        self.query_one("#machine-id-hint", Label).update(self._hint(event.value))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not value or value == self._current:
            self.dismiss(None)
            return
        # It becomes a directory name under configs/ — keep it to one segment.
        if "/" in value or value in (".", ".."):
            self.notify("Machine id must be a plain directory name", severity="error")
            return
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)
