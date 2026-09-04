"""ToolTamer TUI - main application."""


from textual.app import App

from tui.core.config import TTConfig
from tui.core.system import SystemInfo, default_base
from tui.screens.dashboard import DashboardScreen


class ToolTamerApp(App):
    """ToolTamer terminal user interface."""

    TITLE = "ToolTamer"
    SUB_TITLE = "v2.0"
    CSS_PATH = "styles.tcss"

    def __init__(self):
        super().__init__()
        base = default_base()
        self._tt_config = TTConfig(base)
        self._system = SystemInfo(base)

    def on_mount(self) -> None:
        self.push_screen(DashboardScreen(self._tt_config, self._system))


def main():
    app = ToolTamerApp()
    app.run()


if __name__ == "__main__":
    main()
