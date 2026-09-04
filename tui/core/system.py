"""Detect OS, package manager, and installed packages."""

import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path

from tui.core.machine_id import read_machine_id


def default_base() -> Path:
    """The ToolTamer base dir: $TT_BASE, else ~/.config/toolTamer."""
    return Path(os.environ.get("TT_BASE", str(Path.home() / ".config" / "toolTamer")))


class SystemInfo:
    """Detects and caches system information."""

    def __init__(self, base: Path | None = None):
        self.os_type = platform.system()
        # What the network calls this machine right now; only shown, never
        # used to pick a config.
        self.real_hostname = socket.gethostname()
        # The name every config lookup keys on. $BASE/machine-id pins it so
        # a VPN or a different DHCP domain does not switch host configs.
        self.hostname = read_machine_id(base or default_base()) or self.real_hostname
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

    def list_dependency_packages(self) -> set[str]:
        """Names of installed packages the package manager considers
        dependency-only installs — not explicitly requested by the user.
        Empty set on any failure or for an unrecognized installer; this is
        a display-only lookup and must never raise."""
        try:
            if self.installer == "brew":
                result = subprocess.run(
                    ["brew", "list", "--no-installed-on-request"],
                    capture_output=True, text=True, timeout=30,
                )
                return {l for l in result.stdout.splitlines() if l.strip()}
            elif self.installer == "apt":
                result = subprocess.run(
                    ["apt-mark", "showauto"],
                    capture_output=True, text=True, timeout=30,
                )
                return {l for l in result.stdout.splitlines() if l.strip()}
            elif self.installer == "pacman":
                result = subprocess.run(
                    ["pacman", "-Qdq"],
                    capture_output=True, text=True, timeout=30,
                )
                return {l for l in result.stdout.splitlines() if l.strip()}
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return set()
        return set()

    def get_required_by(self, package: str) -> list[str]:
        """Names of currently-installed packages that structurally require
        `package` right now — a reverse-dependency lookup, distinct from
        list_dependency_packages()'s install-reason ("auto" vs "manual")
        check. A package can be "manual" and still be required by another
        installed package, in which case the package manager will refuse
        to remove it regardless. Empty list on any failure or for an
        unrecognized installer; this is a display-only lookup and must
        never raise or block an uninstall attempt on its own."""
        try:
            if self.installer == "brew":
                result = subprocess.run(
                    ["brew", "uses", "--installed", package],
                    capture_output=True, text=True, timeout=15,
                )
                return [l.strip() for l in result.stdout.splitlines() if l.strip()]
            elif self.installer == "apt":
                # --important restricts this to Depends/Pre-Depends —
                # without it, apt-cache rdepends also counts Recommends/
                # Suggests/Conflicts/Breaks/Replaces/Enhances as "reverse
                # depends", which are common enough on real systems to
                # make this falsely refuse (or warn about) an uninstall
                # that would actually be fine.
                result = subprocess.run(
                    ["apt-cache", "rdepends", "--installed", "--important", package],
                    capture_output=True, text=True, timeout=15,
                )
                deps = []
                in_deps = False
                for line in result.stdout.splitlines():
                    if line.strip() == "Reverse Depends:":
                        in_deps = True
                        continue
                    if in_deps:
                        name = line.strip().lstrip("|").strip()
                        if name:
                            deps.append(name)
                return deps
            elif self.installer == "pacman":
                result = subprocess.run(
                    ["pacman", "-Qi", package],
                    capture_output=True, text=True, timeout=15,
                )
                for line in result.stdout.splitlines():
                    if line.startswith("Required By"):
                        _, _, value = line.partition(":")
                        names = value.strip()
                        if not names or names == "None":
                            return []
                        return names.split()
                return []
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

    def list_package_full_names(self) -> dict[str, str]:
        """Short name -> fully qualified name, for every installed package
        that comes from a third-party tap.

        A package from such a tap only installs on a machine where its tap
        is already tapped — `brew install clawtunes` fails there, while
        `brew install forketyfork/tap/clawtunes` works because brew taps
        automatically when given a fully qualified name. That's what makes
        the qualified form the right thing to store in a config.

        One bulk call for all installed packages (unlike get_package_tap,
        which is per-package), because this is used to audit whole configs.
        Core/cask-core packages are excluded — they need no qualification.
        Empty dict for non-brew installers (no tap concept) or any
        failure."""
        if self.installer != "brew":
            return {}
        try:
            result = subprocess.run(
                ["brew", "info", "--json=v2", "--installed"],
                capture_output=True, text=True, timeout=60,
            )
            import json
            data = json.loads(result.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            return {}

        mapping: dict[str, str] = {}
        for formula in data.get("formulae", []) or []:
            tap = formula.get("tap")
            name, full = formula.get("name"), formula.get("full_name")
            if tap and tap != "homebrew/core" and name and full and name != full:
                mapping[name] = full
        for cask in data.get("casks", []) or []:
            tap = cask.get("tap")
            name, full = cask.get("token"), cask.get("full_token")
            if tap and tap != "homebrew/cask" and name and full and name != full:
                mapping[name] = full
        return mapping

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
