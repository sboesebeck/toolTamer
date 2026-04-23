"""Main dashboard screen with status and menu."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView

from tui.core.config import TTConfig
from tui.core.system import SystemInfo
from tui.widgets.config_tree import ConfigHierarchy
from tui.widgets.status_bar import StatusBar

# Map menu index to action name
MENU_ACTIONS = [
    "sync_system",
    "sync_files",
    "snapshot",
    "packages",
    "files",
    "git",
]


class MenuItem(ListItem):
    """A menu item with key, label, and description."""

    def __init__(self, key: str, label: str, desc: str, action: str):
        super().__init__()
        self._key = key
        self._label = label
        self._desc = desc
        self.action_name = action

    def compose(self) -> ComposeResult:
        yield Label(
            f"[bold yellow]{self._key}[/]  "
            f"{self._label}  "
            f"[dim]{self._desc}[/]"
        )


class DashboardScreen(Screen):
    """Main dashboard with status overview and action menu."""

    BINDINGS = [
        ("u", "menu_action('sync_system')", "Update System"),
        ("f", "menu_action('sync_files')", "Files Only"),
        ("s", "menu_action('snapshot')", "Snapshot"),
        ("p", "menu_action('packages')", "Packages"),
        ("t", "menu_action('taps')", "Taps"),
        ("d", "menu_action('files')", "Files"),
        ("g", "menu_action('git')", "Git"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, tt_config: TTConfig, system: SystemInfo):
        super().__init__()
        self._tt_config = tt_config
        self._system = system

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="dashboard"):
            with Container(id="status-panel"):
                yield Label("Status", classes="section-title")
                yield StatusBar(
                    tt_config=self._tt_config,
                    system=self._system,
                )
            with Container(id="hierarchy-panel"):
                yield Label("Config Hierarchy", classes="section-title")
                yield ConfigHierarchy(self._tt_config, self._system.hostname)
            with Container(id="menu-panel"):
                yield Label("Actions", classes="section-title")
                yield ListView(
                    MenuItem("U", "Update System", "packages + files + scripts", "sync_system"),
                    MenuItem("F", "Files Only", "sync config files", "sync_files"),
                    MenuItem("S", "Snapshot", "capture state to ToolTamer", "snapshot"),
                    MenuItem("P", "Package Manager", "move, add, compare packages", "packages"),
                    MenuItem("T", "Tap Manager", "manage Homebrew taps", "taps"),
                    MenuItem("D", "File Manager", "move, diff config files", "files"),
                    MenuItem("G", "Git", "open lazygit", "git"),
                )
        yield Footer()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle Enter key on a menu item."""
        item = event.item
        if isinstance(item, MenuItem):
            self.action_menu_action(item.action_name)

    def action_menu_action(self, action: str) -> None:
        if action == "packages":
            from tui.screens.packages import PackageScreen
            self.app.push_screen(PackageScreen(self._tt_config, self._system))
        elif action == "taps":
            from tui.screens.taps import TapScreen
            self.app.push_screen(TapScreen(self._tt_config, self._system))
        elif action == "files":
            from tui.screens.files import FileScreen
            self.app.push_screen(FileScreen(self._tt_config, self._system))
        elif action == "sync_system":
            from tui.screens.sync import SyncScreen
            self.app.push_screen(SyncScreen(self._tt_config, self._system, mode="full"))
        elif action == "sync_files":
            from tui.screens.sync import SyncScreen
            self.app.push_screen(SyncScreen(self._tt_config, self._system, mode="files"))
        elif action == "snapshot":
            from tui.screens.sync import SyncScreen
            self.app.push_screen(SyncScreen(self._tt_config, self._system, mode="snapshot"))
        elif action == "git":
            import subprocess
            self.app.suspend()
            subprocess.run(["lazygit"], cwd=str(self._tt_config.base))

    def action_quit(self) -> None:
        self.app.exit()
