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
