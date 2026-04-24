"""Sync screen — suspends TUI and runs tt in the real terminal."""

import subprocess
from pathlib import Path

from textual.screen import Screen

from tui.core.config import TTConfig
from tui.core.system import SystemInfo


class SyncScreen(Screen):
    """Run sync operations in the real terminal (suspended TUI)."""

    def __init__(self, tt_config: TTConfig, system: SystemInfo, mode: str = "full"):
        super().__init__()
        self._tt_config = tt_config
        self._system = system
        self._mode = mode

    def on_mount(self) -> None:
        # Find tt script
        tt_script = None
        for candidate in [
            Path.home() / "toolTamer" / "bin" / "tt",
            Path("/usr/local/bin/tt"),
        ]:
            if candidate.exists():
                tt_script = candidate
                break

        flag_map = {
            "full": "--syncSys",
            "files": "--syncFilesOnly",
            "snapshot": "--updateToolTamerFiles",
        }
        flag = flag_map.get(self._mode, "--syncSys")

        if tt_script is None:
            self.notify("tt script not found", severity="error")
            self.dismiss(None)
            return

        with self.app.suspend():
            result = subprocess.run(["bash", str(tt_script), flag])

        if result.returncode == 0:
            self.notify("Sync complete", severity="information")
        else:
            self.notify(f"Sync failed (exit {result.returncode})", severity="error")

        self.dismiss(None)
