"""Status summary widget for the dashboard."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Label


class StatusBar(Widget):
    """Shows host, OS, installer info."""

    def __init__(self, host: str, os_type: str, installer: str, **kwargs):
        super().__init__(**kwargs)
        self._host = host
        self._os_type = os_type
        self._installer = installer

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("Host ", classes="label-key")
            yield Label(self._host, classes="label-value", id="host-value")
        with Horizontal():
            yield Label("OS ", classes="label-key")
            yield Label(f"{self._os_type}  ({self._installer})", classes="label-value")
