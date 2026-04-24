"""Detect OS, package manager, and installed packages."""

import platform
import shutil
import socket
import subprocess


class SystemInfo:
    """Detects and caches system information."""

    def __init__(self):
        self.os_type = platform.system()
        self.hostname = socket.gethostname()
        self.installer = self._detect_installer()

    def _detect_installer(self) -> str:
        if self.os_type == "Darwin":
            return "brew"
        if shutil.which("apt"):
            return "apt"
        if shutil.which("pacman"):
            return "pacman"
        return "unknown"

    @property
    def update_commands(self) -> list[list[str]]:
        """Return the package manager update+upgrade commands."""
        cmds = {
            "brew": [["brew", "update"], ["brew", "upgrade"]],
            "apt": [["sudo", "apt-get", "update"], ["sudo", "apt-get", "upgrade", "-y"]],
            "pacman": [["sudo", "pacman", "-Syu", "--noconfirm"]],
        }
        return cmds.get(self.installer, [])

    def list_installed_packages(self) -> list[str]:
        try:
            if self.installer == "brew":
                result = subprocess.run(
                    ["brew", "list", "-1"],
                    capture_output=True, text=True, timeout=30,
                )
                return [l for l in result.stdout.splitlines() if l.strip()]
            elif self.installer == "apt":
                result = subprocess.run(
                    ["dpkg-query", "-f", "${Package}\n", "-W"],
                    capture_output=True, text=True, timeout=30,
                )
                return [l for l in result.stdout.splitlines() if l.strip()]
            elif self.installer == "pacman":
                result = subprocess.run(
                    ["pacman", "-Q"],
                    capture_output=True, text=True, timeout=30,
                )
                return [l.split()[0] for l in result.stdout.splitlines() if l.strip()]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []
        return []

    def sync_taps(self, taps: list[str]) -> list[str]:
        """Ensure all given brew taps are tapped. Returns list of newly added taps."""
        if self.installer != "brew":
            return []
        try:
            result = subprocess.run(
                ["brew", "tap"], capture_output=True, text=True, timeout=10,
            )
            current = set(result.stdout.splitlines())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

        added = []
        for tap in taps:
            if tap not in current:
                try:
                    subprocess.run(
                        ["brew", "tap", tap],
                        capture_output=True, text=True, timeout=60,
                    )
                    added.append(tap)
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    pass
        return added

    def get_package_tap(self, package: str) -> str | None:
        """Get the tap a brew package comes from, or None for core."""
        if self.installer != "brew":
            return None
        try:
            result = subprocess.run(
                ["brew", "info", "--json=v2", package],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return None
            import json
            data = json.loads(result.stdout)
            # Check formulae
            for f in data.get("formulae", []):
                tap = f.get("tap")
                if tap and tap != "homebrew/core":
                    return tap
            # Check casks
            for c in data.get("casks", []):
                tap = c.get("tap")
                if tap and tap != "homebrew/cask":
                    return tap
        except Exception:
            pass
        return None

    def search_package_in_taps(self, package: str) -> str | None:
        """Search for a package across all tapped repos. Returns full name or None."""
        if self.installer != "brew":
            return None
        try:
            result = subprocess.run(
                ["brew", "search", package],
                capture_output=True, text=True, timeout=15,
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                # Look for tap/name format matching our package name
                if "/" in line and line.rsplit("/", 1)[-1] == package:
                    return line
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def list_current_taps(self) -> list[str]:
        """List currently tapped brew taps."""
        if self.installer != "brew":
            return []
        try:
            result = subprocess.run(
                ["brew", "tap"], capture_output=True, text=True, timeout=10,
            )
            return [l.strip() for l in result.stdout.splitlines() if l.strip()]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

    def install_package(self, package: str) -> tuple[bool, str]:
        """Install a package. Returns (success, output)."""
        cmds = {
            "brew": ["brew", "install", package],
            "apt": ["sudo", "apt", "install", "-y", package],
            "pacman": ["sudo", "pacman", "-Sy", "--noconfirm", package],
        }
        cmd = cmds.get(self.installer)
        if not cmd:
            return False, f"Unknown installer: {self.installer}"
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
            )
            output = result.stdout + result.stderr
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, "Installation timed out"
        except FileNotFoundError:
            return False, f"{self.installer} not found"

    def uninstall_package(self, package: str) -> tuple[bool, str]:
        """Uninstall a package. Returns (success, output)."""
        cmds = {
            "brew": ["brew", "uninstall", package],
            "apt": ["sudo", "apt", "purge", "-y", package],
            "pacman": ["sudo", "pacman", "-R", "--noconfirm", package],
        }
        cmd = cmds.get(self.installer)
        if not cmd:
            return False, f"Unknown installer: {self.installer}"
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
            )
            output = result.stdout + result.stderr
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, "Uninstall timed out"
        except FileNotFoundError:
            return False, f"{self.installer} not found"

    def get_package_info(self, package: str) -> str:
        try:
            if self.installer == "brew":
                result = subprocess.run(
                    ["brew", "info", package],
                    capture_output=True, text=True, timeout=10,
                )
                return result.stdout
            elif self.installer == "apt":
                result = subprocess.run(
                    ["apt-cache", "show", package],
                    capture_output=True, text=True, timeout=10,
                )
                return result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return f"No info available for {package}"
        return f"No info available for {package}"
