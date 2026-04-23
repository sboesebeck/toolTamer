# ToolTamer Textual TUI Rewrite

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fzf-based Bash menus with a professional Python/Textual TUI featuring a status dashboard, package manager with hierarchy move/copy, file manager with diff preview, and live sync output — while keeping the existing Bash core scripts as the backend.

**Architecture:** A Python package (`tui/`) in the toolTamer repo provides the Textual-based frontend. A `core/` subpackage reads config files and detects the system. TUI screens call existing Bash functions via subprocess workers for sync operations. The entry point is `bin/tt-tui` (a thin Python wrapper). The existing `bin/tt` Bash script remains functional for headless/scripted use.

**Tech Stack:** Python 3.12, Textual 1.x, pytest, subprocess for Bash bridge

---

## File Structure

```
~/toolTamer/
├── bin/
│   ├── tt              (existing Bash - unchanged)
│   ├── include.sh      (existing - unchanged)
│   ├── admin.sh        (existing - unchanged)
│   └── tt-tui          (NEW - Python entry point script)
├── tui/
│   ├── __init__.py     (NEW - package marker)
│   ├── app.py          (NEW - main Textual App, screen routing, global bindings)
│   ├── styles.tcss     (NEW - all Textual CSS styles)
│   ├── core/
│   │   ├── __init__.py (NEW - package marker)
│   │   ├── config.py   (NEW - read/write config hierarchy, files.conf, to_install.*)
│   │   └── system.py   (NEW - OS detection, package manager, installed package listing)
│   ├── screens/
│   │   ├── __init__.py (NEW - package marker)
│   │   ├── dashboard.py(NEW - main dashboard with status + menu)
│   │   ├── packages.py (NEW - package manager with hierarchy move/copy)
│   │   ├── files.py    (NEW - file manager with diff preview)
│   │   └── sync.py     (NEW - live sync output screen)
│   └── widgets/
│       ├── __init__.py (NEW - package marker)
│       ├── config_tree.py  (NEW - config hierarchy tree widget)
│       └── status_bar.py   (NEW - status summary widget)
├── tests/
│   ├── __init__.py     (NEW)
│   ├── conftest.py     (NEW - shared fixtures: temp config dirs, mock configs)
│   ├── test_config.py  (NEW - tests for tui.core.config)
│   ├── test_system.py  (NEW - tests for tui.core.system)
│   ├── test_dashboard.py  (NEW - Textual pilot tests for dashboard)
│   └── test_packages.py   (NEW - Textual pilot tests for package screen)
├── pyproject.toml      (NEW - Python project config)
├── docs/
├── mkdocs.yml
├── AGENTS.md
└── README.md
```

---

### Task 1: Project Setup

**Files:**
- Create: `pyproject.toml`
- Create: `tui/__init__.py`
- Create: `tui/core/__init__.py`
- Create: `tui/screens/__init__.py`
- Create: `tui/widgets/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "tooltamer-tui"
version = "2.0.0"
description = "ToolTamer - cross-platform config & package sync TUI"
requires-python = ">=3.12"
dependencies = [
    "textual>=1.0.0,<2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "textual-dev>=1.0.0",
]

[project.scripts]
tt-tui = "tui.app:main"
```

- [ ] **Step 2: Create package init files**

`tui/__init__.py`:
```python
"""ToolTamer TUI - Professional terminal interface for ToolTamer."""
```

`tui/core/__init__.py`:
```python
"""Core logic for config reading and system detection."""
```

`tui/screens/__init__.py`:
```python
"""Textual screens for ToolTamer TUI."""
```

`tui/widgets/__init__.py`:
```python
"""Custom Textual widgets for ToolTamer TUI."""
```

`tests/__init__.py`:
```python
```

- [ ] **Step 3: Create test fixtures**

`tests/conftest.py`:
```python
from pathlib import Path
import pytest


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """Create a minimal ToolTamer config structure for testing."""
    base = tmp_path / "toolTamer"
    configs = base / "configs"

    # common config
    common = configs / "common"
    common.mkdir(parents=True)
    (common / "files").mkdir()
    (common / "to_install.brew").write_text("git\nfzf\ncurl\nbat\n")
    (common / "to_install.apt").write_text("git\ncurl\n")
    (common / "files.conf").write_text(
        "zshrc;.zshrc\nstarship.toml;.config/starship.toml\n"
    )

    # shared macosx config
    macosx = configs / "macosx"
    macosx.mkdir(parents=True)
    (macosx / "files").mkdir()
    (macosx / "to_install.brew").write_text("aerospace\nghostty\ntopgrade\n")
    (macosx / "files.conf").write_text("aerospace.toml;.aerospace.toml\n")
    (macosx / "includes.conf").write_text("")

    # host-specific config
    host = configs / "testhost"
    host.mkdir(parents=True)
    (host / "files").mkdir()
    (host / "to_install.brew").write_text("ollama\npostgresql\n")
    (host / "to_install.apt").write_text("docker\n")
    (host / "files.conf").write_text("kitty.conf;.config/kitty/kitty.conf\n")
    (host / "includes.conf").write_text("macosx\n")
    (host / "taps").write_text("nikitabobko/tap\n")

    # tt.conf
    (base / "tt.conf").write_text("GIT_AUTO_UPDATE=ask\n")

    return base


@pytest.fixture
def sample_files(tmp_config: Path) -> Path:
    """Add sample managed files to the config."""
    common_files = tmp_config / "configs" / "common" / "files"
    (common_files / "zshrc").write_text("# zshrc content\nexport PATH=$PATH\n")
    (common_files / "starship.toml").write_text("[character]\nsymbol = '> '\n")

    macosx_files = tmp_config / "configs" / "macosx" / "files"
    (macosx_files / "aerospace.toml").write_text("[mode.main.binding]\n")

    host_files = tmp_config / "configs" / "testhost" / "files"
    (host_files / "kitty.conf").write_text("font_size 14\n")

    return tmp_config
```

- [ ] **Step 4: Create venv and install dependencies**

Run:
```bash
cd ~/toolTamer
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: No errors, `textual` importable.

- [ ] **Step 5: Verify setup**

Run:
```bash
cd ~/toolTamer
source .venv/bin/activate
python -c "import textual; print(textual.__version__)"
pytest tests/ --co -q
```

Expected: Textual version printed, `conftest.py` collected (0 tests yet).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tui/ tests/
git commit -m "feat: set up Python/Textual project structure for TUI rewrite"
```

---

### Task 2: Core Config Module

**Files:**
- Create: `tui/core/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for config reading**

`tests/test_config.py`:
```python
from pathlib import Path
from tui.core.config import TTConfig


def test_list_configs(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    names = cfg.list_configs()
    assert "common" in names
    assert "macosx" in names
    assert "testhost" in names


def test_get_includes(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    includes = cfg.get_includes("testhost")
    assert includes == ["macosx"]


def test_get_includes_common_has_none(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    includes = cfg.get_includes("common")
    assert includes == []


def test_get_parents(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    parents = cfg.get_parents("testhost")
    assert "common" in parents
    assert "macosx" in parents


def test_get_packages(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    pkgs = cfg.get_packages("testhost", "brew")
    assert "ollama" in pkgs
    assert "postgresql" in pkgs


def test_get_effective_packages(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    effective = cfg.get_effective_packages("testhost", "brew")
    # common + macosx + testhost
    assert "git" in effective  # from common
    assert "aerospace" in effective  # from macosx
    assert "ollama" in effective  # from testhost


def test_get_files_conf(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    files = cfg.get_file_mappings("testhost")
    assert ("kitty.conf", ".config/kitty/kitty.conf") in files


def test_get_effective_file_mappings(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    mappings = cfg.get_effective_file_mappings("testhost")
    targets = [m.target for m in mappings]
    assert ".config/kitty/kitty.conf" in targets  # testhost
    assert ".aerospace.toml" in targets  # macosx
    assert ".zshrc" in targets  # common


def test_resolve_chain(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    chain = cfg.resolve_chain("testhost")
    assert chain == ["common", "macosx", "testhost"]


def test_move_package(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    cfg.move_package("testhost", "common", "ollama", "brew")
    # Removed from source
    assert "ollama" not in cfg.get_packages("testhost", "brew")
    # Added to destination
    assert "ollama" in cfg.get_packages("common", "brew")


def test_copy_package(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    cfg.copy_package("testhost", "common", "ollama", "brew")
    # Still in source
    assert "ollama" in cfg.get_packages("testhost", "brew")
    # Also in destination
    assert "ollama" in cfg.get_packages("common", "brew")


def test_get_taps(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    taps = cfg.get_taps("testhost")
    assert "nikitabobko/tap" in taps


def test_get_children(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    children = cfg.get_children("macosx")
    assert "testhost" in children
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/toolTamer && source .venv/bin/activate && pytest tests/test_config.py -v`

Expected: All tests FAIL with `ModuleNotFoundError: No module named 'tui.core.config'`

- [ ] **Step 3: Implement TTConfig**

`tui/core/config.py`:
```python
"""Read and manipulate ToolTamer configuration hierarchy."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileMapping:
    """A single file mapping entry from files.conf."""
    stored: str    # filename in config's files/ directory
    target: str    # destination relative to $HOME
    config: str    # which config this came from
    repo_path: Path  # absolute path to the file in the repo


class TTConfig:
    """Interface to the ToolTamer config directory."""

    def __init__(self, base: Path):
        self.base = Path(base)
        self.configs_dir = self.base / "configs"

    def list_configs(self) -> list[str]:
        """List all config names (excluding symlinks)."""
        if not self.configs_dir.exists():
            return []
        return sorted(
            d.name
            for d in self.configs_dir.iterdir()
            if d.is_dir() and not d.is_symlink()
        )

    def get_includes(self, config: str) -> list[str]:
        """Get direct includes for a config."""
        inc_file = self.configs_dir / config / "includes.conf"
        if not inc_file.exists():
            return []
        lines = inc_file.read_text().splitlines()
        return [
            line.strip()
            for line in lines
            if line.strip() and not line.strip().startswith("#")
        ]

    def resolve_chain(self, config: str) -> list[str]:
        """Resolve the full include chain: common -> includes -> config."""
        chain = ["common"]
        for inc in self.get_includes(config):
            if inc not in chain:
                chain.append(inc)
        if config not in chain:
            chain.append(config)
        return chain

    def get_parents(self, config: str) -> list[str]:
        """Get all parent configs (common + includes)."""
        if config == "common":
            return []
        parents = ["common"]
        for inc in self.get_includes(config):
            if inc not in parents:
                parents.append(inc)
        return parents

    def get_children(self, config: str) -> list[str]:
        """Get configs that include this config."""
        children = []
        for cfg in self.list_configs():
            if cfg == config:
                continue
            if config in self.get_includes(cfg):
                children.append(cfg)
            elif config == "common":
                # common is implicit parent of everything
                pass
        return children

    def get_packages(self, config: str, installer: str) -> list[str]:
        """Get packages listed directly in a config's install file."""
        pkg_file = self.configs_dir / config / f"to_install.{installer}"
        if not pkg_file.exists():
            return []
        return [
            line.strip()
            for line in pkg_file.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def get_effective_packages(self, config: str, installer: str) -> list[str]:
        """Get all packages for a config including inherited ones."""
        seen = set()
        result = []
        for cfg in self.resolve_chain(config):
            for pkg in self.get_packages(cfg, installer):
                if pkg not in seen:
                    seen.add(pkg)
                    result.append(pkg)
        return result

    def get_file_mappings(self, config: str) -> list[tuple[str, str]]:
        """Get raw (stored, target) pairs from a config's files.conf."""
        conf_file = self.configs_dir / config / "files.conf"
        if not conf_file.exists():
            return []
        mappings = []
        for line in conf_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ";" not in line:
                continue
            stored, target = line.split(";", 1)
            stored = stored.strip()
            target = target.strip()
            if stored and target:
                mappings.append((stored, target))
        return mappings

    def get_effective_file_mappings(self, config: str) -> list[FileMapping]:
        """Get the effective file mappings after hierarchy resolution.

        Later configs override earlier ones for the same target.
        """
        by_target: dict[str, FileMapping] = {}
        for cfg in self.resolve_chain(config):
            for stored, target in self.get_file_mappings(cfg):
                repo_path = self.configs_dir / cfg / "files" / stored
                by_target[target] = FileMapping(
                    stored=stored,
                    target=target,
                    config=cfg,
                    repo_path=repo_path,
                )
        return list(by_target.values())

    def get_taps(self, config: str) -> list[str]:
        """Get brew taps for a config."""
        taps_file = self.configs_dir / config / "taps"
        if not taps_file.exists():
            return []
        return [
            line.strip()
            for line in taps_file.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def move_package(
        self, source: str, dest: str, package: str, installer: str
    ) -> None:
        """Move a package from one config to another."""
        self._remove_package(source, package, installer)
        self._add_package(dest, package, installer)

    def copy_package(
        self, source: str, dest: str, package: str, installer: str
    ) -> None:
        """Copy a package from one config to another (keep in source)."""
        self._add_package(dest, package, installer)

    def _add_package(self, config: str, package: str, installer: str) -> None:
        pkg_file = self.configs_dir / config / f"to_install.{installer}"
        existing = self.get_packages(config, installer)
        if package not in existing:
            with pkg_file.open("a") as f:
                f.write(f"{package}\n")

    def _remove_package(
        self, config: str, package: str, installer: str
    ) -> None:
        pkg_file = self.configs_dir / config / f"to_install.{installer}"
        if not pkg_file.exists():
            return
        lines = pkg_file.read_text().splitlines()
        filtered = [l for l in lines if l.strip() != package]
        pkg_file.write_text("\n".join(filtered) + "\n" if filtered else "")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/toolTamer && source .venv/bin/activate && pytest tests/test_config.py -v`

Expected: All 13 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tui/core/config.py tests/test_config.py
git commit -m "feat: add TTConfig for reading/writing config hierarchy"
```

---

### Task 3: System Detection Module

**Files:**
- Create: `tui/core/system.py`
- Create: `tests/test_system.py`

- [ ] **Step 1: Write failing tests**

`tests/test_system.py`:
```python
import platform
from unittest.mock import patch
from tui.core.system import SystemInfo


def test_detect_os():
    info = SystemInfo()
    assert info.os_type in ("Darwin", "Linux")


def test_installer_darwin():
    with patch("platform.system", return_value="Darwin"):
        info = SystemInfo()
        assert info.installer == "brew"


def test_installer_linux_apt():
    with patch("platform.system", return_value="Linux"):
        with patch("shutil.which", side_effect=lambda x: "/usr/bin/apt" if x == "apt" else None):
            info = SystemInfo()
            assert info.installer == "apt"


def test_hostname():
    info = SystemInfo()
    assert len(info.hostname) > 0


def test_list_installed_packages_returns_list():
    info = SystemInfo()
    # Just verify it returns a list without error
    pkgs = info.list_installed_packages()
    assert isinstance(pkgs, list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_system.py -v`

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement SystemInfo**

`tui/core/system.py`:
```python
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
        """List currently installed packages via the system package manager."""
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
        """Get info string for a package."""
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_system.py -v`

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tui/core/system.py tests/test_system.py
git commit -m "feat: add SystemInfo for OS and package manager detection"
```

---

### Task 4: Textual CSS Styles

**Files:**
- Create: `tui/styles.tcss`

- [ ] **Step 1: Write the complete stylesheet**

`tui/styles.tcss`:
```css
/* ── Global ── */
Screen {
    background: $surface;
}

/* ── Dashboard ── */
#dashboard {
    layout: grid;
    grid-size: 2 2;
    grid-gutter: 1;
    padding: 1 2;
}

#status-panel {
    row-span: 1;
    border: round $accent;
    padding: 1 2;
    height: auto;
    max-height: 12;
}

#status-panel .label-key {
    color: $text-muted;
    width: 12;
}

#status-panel .label-value {
    color: $text;
    text-style: bold;
}

#hierarchy-panel {
    row-span: 1;
    border: round $accent;
    padding: 1 2;
    height: auto;
    max-height: 12;
}

#hierarchy-panel Tree {
    height: auto;
    max-height: 8;
}

#menu-panel {
    column-span: 2;
    border: round $primary;
    padding: 1 2;
    height: auto;
}

#menu-panel ListView {
    height: auto;
}

#menu-panel ListItem {
    padding: 0 2;
    height: 3;
}

#menu-panel ListItem:hover {
    background: $boost;
}

#menu-panel ListItem.--highlight {
    background: $accent 20%;
}

#menu-panel .menu-key {
    color: $warning;
    text-style: bold;
    width: 3;
}

#menu-panel .menu-label {
    color: $text;
}

#menu-panel .menu-desc {
    color: $text-muted;
}

/* ── Package Screen ── */
#pkg-screen {
    layout: horizontal;
}

#pkg-list-pane {
    width: 1fr;
    border: round $accent;
    padding: 0 1;
}

#pkg-info-pane {
    width: 1fr;
    border: round $primary;
    padding: 1 2;
}

#pkg-list-pane DataTable {
    height: 1fr;
}

#pkg-info-pane RichLog {
    height: 1fr;
}

.pkg-status-synced {
    color: $success;
}

.pkg-status-missing {
    color: $error;
}

.pkg-status-excess {
    color: $warning;
}

.config-tag-parent {
    color: $accent;
}

.config-tag-child {
    color: $primary;
}

.config-tag-host {
    color: $success;
    text-style: bold;
}

/* ── File Screen ── */
#file-screen {
    layout: horizontal;
}

#file-list-pane {
    width: 1fr;
    border: round $accent;
    padding: 0 1;
}

#file-diff-pane {
    width: 1fr;
    border: round $primary;
    padding: 1 2;
}

#file-list-pane DataTable {
    height: 1fr;
}

#file-diff-pane RichLog {
    height: 1fr;
}

/* ── Sync Screen ── */
#sync-screen {
    layout: vertical;
    padding: 1 2;
}

#sync-screen RichLog {
    height: 1fr;
    border: round $accent;
}

#sync-progress {
    height: 3;
    dock: bottom;
    padding: 0 2;
}

/* ── Shared ── */
.section-title {
    text-style: bold;
    color: $primary;
    padding: 0 0 1 0;
}

.help-text {
    color: $text-muted;
    dock: bottom;
    height: 1;
    padding: 0 1;
}
```

- [ ] **Step 2: Commit**

```bash
git add tui/styles.tcss
git commit -m "feat: add Textual CSS styles for all TUI screens"
```

---

### Task 5: Dashboard Screen + Main App

**Files:**
- Create: `tui/app.py`
- Create: `tui/widgets/config_tree.py`
- Create: `tui/widgets/status_bar.py`
- Create: `tui/screens/dashboard.py`
- Create: `bin/tt-tui`
- Create: `tests/test_dashboard.py`

- [ ] **Step 1: Write failing test for dashboard**

`tests/test_dashboard.py`:
```python
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from textual.widgets import Header, Footer, ListView, Tree

from tui.app import ToolTamerApp


@pytest.fixture
def app(tmp_config: Path) -> ToolTamerApp:
    with patch.dict(os.environ, {"TT_BASE": str(tmp_config)}):
        with patch("socket.gethostname", return_value="testhost"):
            return ToolTamerApp()


@pytest.mark.asyncio
async def test_dashboard_has_header_and_footer(app: ToolTamerApp):
    async with app.run_test() as pilot:
        assert app.query_one(Header)
        assert app.query_one(Footer)


@pytest.mark.asyncio
async def test_dashboard_shows_hostname(app: ToolTamerApp):
    async with app.run_test() as pilot:
        text = app.query_one("#host-value").render()
        assert "testhost" in str(text)


@pytest.mark.asyncio
async def test_dashboard_has_menu(app: ToolTamerApp):
    async with app.run_test() as pilot:
        menu = app.query_one(ListView)
        assert menu is not None


@pytest.mark.asyncio
async def test_dashboard_has_config_tree(app: ToolTamerApp):
    async with app.run_test() as pilot:
        tree = app.query_one(Tree)
        assert tree is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard.py -v`

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create ConfigTree widget**

`tui/widgets/config_tree.py`:
```python
"""Config hierarchy tree widget."""

from textual.widgets import Tree

from tui.core.config import TTConfig


class ConfigTree(Tree):
    """Displays the config include hierarchy."""

    def __init__(self, tt_config: TTConfig, host: str, **kwargs):
        super().__init__("configs", **kwargs)
        self._tt_config = tt_config
        self._host = host

    def on_mount(self) -> None:
        self.root.expand()
        self._build_tree()

    def _build_tree(self) -> None:
        self.root.remove_children()
        chain = self._tt_config.resolve_chain(self._host)
        parent_node = self.root
        for cfg in chain:
            pkg_count = len(
                self._tt_config.get_packages(cfg, "brew")
            ) + len(
                self._tt_config.get_packages(cfg, "apt")
            )
            file_count = len(self._tt_config.get_file_mappings(cfg))
            label = f"{cfg}  ({pkg_count} pkg, {file_count} files)"
            if cfg == chain[-1]:
                parent_node = parent_node.add_leaf(label)
            else:
                parent_node = parent_node.add(label)
                parent_node.expand()
```

- [ ] **Step 4: Create StatusBar widget**

`tui/widgets/status_bar.py`:
```python
"""Status summary widget for the dashboard."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Label


class StatusBar(Widget):
    """Shows host, OS, installer, and change counts."""

    def __init__(
        self,
        host: str,
        os_type: str,
        installer: str,
        **kwargs,
    ):
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
            yield Label(
                f"{self._os_type}  ({self._installer})",
                classes="label-value",
            )
```

- [ ] **Step 5: Create Dashboard screen**

`tui/screens/dashboard.py`:
```python
"""Main dashboard screen with status and menu."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import (
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
)

from tui.core.config import TTConfig
from tui.core.system import SystemInfo
from tui.widgets.config_tree import ConfigTree
from tui.widgets.status_bar import StatusBar


class MenuItem(ListItem):
    """A menu item with key, label, and description."""

    def __init__(self, key: str, label: str, desc: str, action: str):
        super().__init__()
        self._key = key
        self._label = label
        self._desc = desc
        self.action_name = action

    def compose(self) -> ComposeResult:
        with Container():
            yield Label(
                f"[bold $warning]{self._key}[/]  "
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
        ("d", "menu_action('files')", "Files"),
        ("c", "menu_action('config')", "Config"),
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
                    host=self._system.hostname,
                    os_type=self._system.os_type,
                    installer=self._system.installer,
                )
            with Container(id="hierarchy-panel"):
                yield Label("Config Hierarchy", classes="section-title")
                yield ConfigTree(
                    self._tt_config, self._system.hostname
                )
            with Container(id="menu-panel"):
                yield Label("Actions", classes="section-title")
                yield ListView(
                    MenuItem("U", "Update System",
                             "packages + files + scripts", "sync_system"),
                    MenuItem("F", "Files Only",
                             "sync config files", "sync_files"),
                    MenuItem("S", "Snapshot",
                             "capture state to ToolTamer", "snapshot"),
                    MenuItem("P", "Package Manager",
                             "move, add, compare packages", "packages"),
                    MenuItem("D", "File Manager",
                             "move, diff config files", "files"),
                    MenuItem("C", "Config Explorer",
                             "view effective config", "config"),
                    MenuItem("G", "Git",
                             "open lazygit", "git"),
                )
        yield Footer()

    def action_menu_action(self, action: str) -> None:
        if action == "packages":
            self.app.push_screen("packages")
        elif action == "files":
            self.app.push_screen("files")
        elif action == "sync_system":
            self.app.push_screen("sync", {"mode": "full"})
        elif action == "sync_files":
            self.app.push_screen("sync", {"mode": "files"})
        elif action == "snapshot":
            self.app.push_screen("sync", {"mode": "snapshot"})
        elif action == "git":
            self.app.action_suspend_process()
            import subprocess
            subprocess.run(["lazygit"], cwd=str(self._tt_config.base))
        elif action == "config":
            pass  # Task 9 will implement this

    def action_quit(self) -> None:
        self.app.exit()
```

- [ ] **Step 6: Create main App**

`tui/app.py`:
```python
"""ToolTamer TUI - main application."""

import os
from pathlib import Path

from textual.app import App

from tui.core.config import TTConfig
from tui.core.system import SystemInfo
from tui.screens.dashboard import DashboardScreen


class ToolTamerApp(App):
    """ToolTamer terminal user interface."""

    TITLE = "ToolTamer"
    SUB_TITLE = "v2.0"
    CSS_PATH = "styles.tcss"

    def __init__(self):
        super().__init__()
        base = Path(os.environ.get("TT_BASE", Path.home() / ".config" / "toolTamer"))
        self._tt_config = TTConfig(base)
        self._system = SystemInfo()

    def on_mount(self) -> None:
        self.push_screen(
            DashboardScreen(self._tt_config, self._system)
        )


def main():
    app = ToolTamerApp()
    app.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Create entry point script**

`bin/tt-tui`:
```python
#!/usr/bin/env python3
"""ToolTamer TUI entry point."""

import sys
from pathlib import Path

# Add repo root to path so tui package is importable
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from tui.app import main

main()
```

Make executable:
```bash
chmod +x ~/toolTamer/bin/tt-tui
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_dashboard.py -v`

Expected: All 4 tests PASS.

- [ ] **Step 9: Manual smoke test**

Run:
```bash
cd ~/toolTamer
source .venv/bin/activate
python -m tui.app
```

Expected: Full-screen TUI with header, status panel, config tree, and action menu. Press `q` to quit.

- [ ] **Step 10: Commit**

```bash
git add tui/app.py tui/screens/dashboard.py tui/widgets/ bin/tt-tui tests/test_dashboard.py
git commit -m "feat: add dashboard screen with status panel, config tree, and action menu"
```

---

### Task 6: Package Manager Screen

This is the main new feature — a unified view of all packages across the hierarchy with move/copy support.

**Files:**
- Create: `tui/screens/packages.py`
- Create: `tests/test_packages.py`

- [ ] **Step 1: Write failing tests**

`tests/test_packages.py`:
```python
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from textual.widgets import DataTable

from tui.app import ToolTamerApp
from tui.screens.packages import PackageScreen


@pytest.fixture
def app(tmp_config: Path) -> ToolTamerApp:
    with patch.dict(os.environ, {"TT_BASE": str(tmp_config)}):
        with patch("socket.gethostname", return_value="testhost"):
            return ToolTamerApp()


@pytest.mark.asyncio
async def test_package_screen_has_table(app: ToolTamerApp):
    async with app.run_test() as pilot:
        screen = PackageScreen(app._tt_config, app._system)
        app.push_screen(screen)
        await pilot.pause()
        table = app.query_one(DataTable)
        assert table is not None


@pytest.mark.asyncio
async def test_package_screen_shows_packages(app: ToolTamerApp):
    async with app.run_test() as pilot:
        screen = PackageScreen(app._tt_config, app._system)
        app.push_screen(screen)
        await pilot.pause()
        table = app.query_one(DataTable)
        assert table.row_count > 0


@pytest.mark.asyncio
async def test_escape_returns_to_dashboard(app: ToolTamerApp):
    async with app.run_test() as pilot:
        screen = PackageScreen(app._tt_config, app._system)
        app.push_screen(screen)
        await pilot.pause()
        await pilot.press("escape")
        assert not isinstance(app.screen, PackageScreen)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_packages.py -v`

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement PackageScreen**

`tui/screens/packages.py`:
```python
"""Package manager screen with hierarchy view and move/copy."""

from textual import work
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import Screen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Label,
    OptionList,
    RichLog,
    Static,
)
from textual.widgets.option_list import Option

from tui.core.config import TTConfig
from tui.core.system import SystemInfo


class PackageScreen(Screen):
    """View and manage packages across the config hierarchy."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("m", "move_package", "Move"),
        ("c", "copy_package", "Copy"),
        ("slash", "filter", "Filter"),
        ("tab", "switch_pane", "Switch Pane"),
    ]

    def __init__(self, tt_config: TTConfig, system: SystemInfo):
        super().__init__()
        self._tt_config = tt_config
        self._system = system
        self._current_config: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="pkg-screen"):
            with Container(id="pkg-list-pane"):
                yield Label("Packages", classes="section-title")
                yield DataTable(id="pkg-table")
            with Container(id="pkg-info-pane"):
                yield Label("Details", classes="section-title")
                yield RichLog(id="pkg-info", wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#pkg-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("St", "Package", "Config")
        self._load_packages()

    def _load_packages(self) -> None:
        table = self.query_one("#pkg-table", DataTable)
        table.clear()
        host = self._system.hostname
        chain = self._tt_config.resolve_chain(host)
        installed = set()

        # Try to get installed list, but don't block if it fails
        try:
            installed = set(self._system.list_installed_packages())
        except Exception:
            pass

        for cfg in chain:
            pkgs = self._tt_config.get_packages(cfg, self._system.installer)
            for pkg in sorted(pkgs):
                if installed:
                    status = "[green]OK[/]" if pkg in installed else "[red]!![/]"
                else:
                    status = "[dim]--[/]"

                tag = ""
                if cfg == host:
                    tag = "[bold green]host[/]"
                elif cfg == "common":
                    tag = "[cyan]common[/]"
                else:
                    tag = f"[blue]{cfg}[/]"

                table.add_row(status, pkg, tag, key=f"{cfg}:{pkg}")

    def on_data_table_row_highlighted(
        self, event: DataTable.RowHighlighted
    ) -> None:
        if event.row_key is None:
            return
        key = str(event.row_key.value)
        if ":" not in key:
            return
        config, pkg = key.split(":", 1)
        self._show_package_info(config, pkg)

    @work(thread=True)
    def _show_package_info(self, config: str, package: str) -> None:
        info_text = self._system.get_package_info(package)
        log = self.query_one("#pkg-info", RichLog)
        self.call_from_thread(log.clear)

        lines = [
            f"[bold]{package}[/]",
            f"Config: [cyan]{config}[/]",
            "",
        ]

        # Show where else this package appears
        chain = self._tt_config.resolve_chain(self._system.hostname)
        also_in = []
        for cfg in chain:
            if cfg == config:
                continue
            if package in self._tt_config.get_packages(
                cfg, self._system.installer
            ):
                also_in.append(cfg)
        if also_in:
            lines.append(f"[yellow]Also in:[/] {', '.join(also_in)}")
            lines.append("")

        lines.append("[dim]--- Package Info ---[/]")
        lines.append(info_text)

        for line in lines:
            self.call_from_thread(log.write, line)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_move_package(self) -> None:
        table = self.query_one("#pkg-table", DataTable)
        row_key = table.cursor_row
        if row_key is None:
            return
        cell_key = table.get_row_at(row_key)
        # Get the key for the highlighted row
        keys = list(table.rows.keys())
        if row_key >= len(keys):
            return
        key = str(keys[row_key].value)
        if ":" not in key:
            return
        source_config, pkg = key.split(":", 1)
        self._show_destination_picker(source_config, pkg, move=True)

    def action_copy_package(self) -> None:
        table = self.query_one("#pkg-table", DataTable)
        row_key = table.cursor_row
        if row_key is None:
            return
        keys = list(table.rows.keys())
        if row_key >= len(keys):
            return
        key = str(keys[row_key].value)
        if ":" not in key:
            return
        source_config, pkg = key.split(":", 1)
        self._show_destination_picker(source_config, pkg, move=False)

    def _show_destination_picker(
        self, source: str, package: str, move: bool
    ) -> None:
        """Push a destination picker screen for move/copy."""
        action = "Move" if move else "Copy"
        from tui.screens._dest_picker import DestPickerScreen
        self.app.push_screen(
            DestPickerScreen(
                self._tt_config,
                self._system,
                source_config=source,
                package=package,
                is_move=move,
            ),
            callback=self._on_dest_picked,
        )

    def _on_dest_picked(self, result: str | None) -> None:
        if result:
            self._load_packages()

    def action_filter(self) -> None:
        # Future: add input filter
        pass

    def action_switch_pane(self) -> None:
        if self.query_one("#pkg-table", DataTable).has_focus:
            self.query_one("#pkg-info", RichLog).focus()
        else:
            self.query_one("#pkg-table", DataTable).focus()
```

- [ ] **Step 4: Create destination picker screen**

`tui/screens/_dest_picker.py`:
```python
"""Destination config picker for package move/copy."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
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

    def __init__(
        self,
        tt_config: TTConfig,
        system: SystemInfo,
        source_config: str,
        package: str,
        is_move: bool,
    ):
        super().__init__()
        self._tt_config = tt_config
        self._system = system
        self._source = source_config
        self._package = package
        self._is_move = is_move

    def compose(self) -> ComposeResult:
        action = "Move" if self._is_move else "Copy"
        with Container(id="dest-dialog"):
            yield Label(
                f"[bold]{action}[/] [cyan]{self._package}[/] "
                f"from [yellow]{self._source}[/] to:",
            )
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

                # Check if package already exists there
                existing = self._tt_config.get_packages(
                    cfg, self._system.installer
                )
                if self._package in existing:
                    tag += " [dim](has pkg)[/]"

                options.append(Option(f"{cfg}{tag}", id=cfg))

            yield OptionList(*options, id="dest-list")

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        dest = str(event.option.id)
        if self._is_move:
            self._tt_config.move_package(
                self._source, dest, self._package, self._system.installer
            )
        else:
            self._tt_config.copy_package(
                self._source, dest, self._package, self._system.installer
            )
        self.dismiss(dest)

    def action_cancel(self) -> None:
        self.dismiss(None)
```

Create `tui/screens/__init__.py` with empty content (already exists from Task 1).

- [ ] **Step 5: Wire PackageScreen into the app**

Update `tui/screens/dashboard.py` — add to the `action_menu_action` method:

In `tui/screens/dashboard.py`, replace the packages case:
```python
        elif action == "packages":
            from tui.screens.packages import PackageScreen
            self.app.push_screen(
                PackageScreen(self._tt_config, self._system)
            )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_packages.py -v`

Expected: All 3 tests PASS.

- [ ] **Step 7: Manual smoke test**

Run:
```bash
cd ~/toolTamer && source .venv/bin/activate && python -m tui.app
```

Press `P` to open Package Manager. Verify:
- Packages listed by config with color-coded status
- Arrow keys navigate, details show on the right
- `m` opens destination picker modal
- `ESC` returns to dashboard

- [ ] **Step 8: Commit**

```bash
git add tui/screens/packages.py tui/screens/_dest_picker.py tests/test_packages.py
git commit -m "feat: add package manager screen with hierarchy move/copy"
```

---

### Task 7: File Manager Screen

**Files:**
- Create: `tui/screens/files.py`

- [ ] **Step 1: Implement FileScreen**

`tui/screens/files.py`:
```python
"""File manager screen with diff preview."""

import hashlib
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, RichLog

from tui.core.config import FileMapping, TTConfig
from tui.core.system import SystemInfo


class FileScreen(Screen):
    """View and manage tracked config files."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("a", "apply_to_system", "Apply to System"),
        ("u", "update_tooltamer", "Update TT"),
        ("tab", "switch_pane", "Switch Pane"),
    ]

    def __init__(self, tt_config: TTConfig, system: SystemInfo):
        super().__init__()
        self._tt_config = tt_config
        self._system = system

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="file-screen"):
            with Container(id="file-list-pane"):
                yield Label("Managed Files", classes="section-title")
                yield DataTable(id="file-table")
            with Container(id="file-diff-pane"):
                yield Label("Diff Preview", classes="section-title")
                yield RichLog(id="file-diff", wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#file-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("St", "Target", "Config")
        self._load_files()

    def _load_files(self) -> None:
        table = self.query_one("#file-table", DataTable)
        table.clear()
        host = self._system.hostname
        mappings = self._tt_config.get_effective_file_mappings(host)
        home = Path.home()

        for m in sorted(mappings, key=lambda x: x.target):
            sys_file = home / m.target
            status = self._file_status(m.repo_path, sys_file)
            status_display = {
                "ok": "[green]OK[/]",
                "modified": "[yellow]!![/]",
                "missing_system": "[red]--[/]",
                "missing_repo": "[red]??[/]",
            }.get(status, "[dim]??[/]")

            table.add_row(
                status_display,
                f"~/{m.target}",
                f"[cyan]{m.config}[/]",
                key=f"{m.config}:{m.stored}:{m.target}",
            )

    def _file_status(self, repo: Path, system: Path) -> str:
        if not repo.exists():
            return "missing_repo"
        if not system.exists():
            return "missing_system"
        repo_hash = hashlib.sha1(repo.read_bytes()).hexdigest()
        sys_hash = hashlib.sha1(system.read_bytes()).hexdigest()
        return "ok" if repo_hash == sys_hash else "modified"

    def on_data_table_row_highlighted(
        self, event: DataTable.RowHighlighted
    ) -> None:
        if event.row_key is None:
            return
        key = str(event.row_key.value)
        parts = key.split(":", 2)
        if len(parts) != 3:
            return
        config, stored, target = parts
        self._show_diff(config, stored, target)

    @work(thread=True)
    def _show_diff(self, config: str, stored: str, target: str) -> None:
        import subprocess

        log = self.query_one("#file-diff", RichLog)
        self.call_from_thread(log.clear)

        repo_file = self._tt_config.configs_dir / config / "files" / stored
        sys_file = Path.home() / target

        lines = [
            f"[bold]~/{target}[/]",
            f"Config: [cyan]{config}[/]",
            f"Repo:   {repo_file}",
            "",
        ]

        if not repo_file.exists():
            lines.append("[red]Repo file missing[/]")
        elif not sys_file.exists():
            lines.append("[red]System file missing[/]")
        else:
            repo_hash = hashlib.sha1(repo_file.read_bytes()).hexdigest()
            sys_hash = hashlib.sha1(sys_file.read_bytes()).hexdigest()
            if repo_hash == sys_hash:
                lines.append("[green]Files are identical[/]")
            else:
                lines.append("[yellow]Files differ:[/]")
                lines.append("")
                try:
                    result = subprocess.run(
                        ["diff", "-u", str(repo_file), str(sys_file)],
                        capture_output=True, text=True, timeout=5,
                    )
                    for diff_line in result.stdout.splitlines()[:100]:
                        if diff_line.startswith("+"):
                            lines.append(f"[green]{diff_line}[/]")
                        elif diff_line.startswith("-"):
                            lines.append(f"[red]{diff_line}[/]")
                        elif diff_line.startswith("@@"):
                            lines.append(f"[cyan]{diff_line}[/]")
                        else:
                            lines.append(diff_line)
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    lines.append("[dim]diff command not available[/]")

        for line in lines:
            self.call_from_thread(log.write, line)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_apply_to_system(self) -> None:
        """Copy repo file to system (overwrite local)."""
        table = self.query_one("#file-table", DataTable)
        row_key = table.cursor_row
        if row_key is None:
            return
        keys = list(table.rows.keys())
        if row_key >= len(keys):
            return
        key = str(keys[row_key].value)
        parts = key.split(":", 2)
        if len(parts) != 3:
            return
        config, stored, target = parts
        repo_file = self._tt_config.configs_dir / config / "files" / stored
        sys_file = Path.home() / target
        if repo_file.exists():
            sys_file.parent.mkdir(parents=True, exist_ok=True)
            sys_file.write_bytes(repo_file.read_bytes())
            self._load_files()
            self._show_diff(config, stored, target)

    def action_update_tooltamer(self) -> None:
        """Copy system file to repo (update ToolTamer)."""
        table = self.query_one("#file-table", DataTable)
        row_key = table.cursor_row
        if row_key is None:
            return
        keys = list(table.rows.keys())
        if row_key >= len(keys):
            return
        key = str(keys[row_key].value)
        parts = key.split(":", 2)
        if len(parts) != 3:
            return
        config, stored, target = parts
        repo_file = self._tt_config.configs_dir / config / "files" / stored
        sys_file = Path.home() / target
        if sys_file.exists():
            repo_file.parent.mkdir(parents=True, exist_ok=True)
            repo_file.write_bytes(sys_file.read_bytes())
            self._load_files()
            self._show_diff(config, stored, target)

    def action_switch_pane(self) -> None:
        if self.query_one("#file-table", DataTable).has_focus:
            self.query_one("#file-diff", RichLog).focus()
        else:
            self.query_one("#file-table", DataTable).focus()
```

- [ ] **Step 2: Wire FileScreen into dashboard**

In `tui/screens/dashboard.py`, update the files case in `action_menu_action`:

```python
        elif action == "files":
            from tui.screens.files import FileScreen
            self.app.push_screen(
                FileScreen(self._tt_config, self._system)
            )
```

- [ ] **Step 3: Manual smoke test**

Run: `cd ~/toolTamer && source .venv/bin/activate && python -m tui.app`

Press `D` to open File Manager. Verify:
- Files listed with status (OK/modified/missing)
- Selecting a row shows diff in right pane
- `a` applies repo → system, `u` updates ToolTamer from system
- `ESC` returns to dashboard

- [ ] **Step 4: Commit**

```bash
git add tui/screens/files.py
git commit -m "feat: add file manager screen with diff preview and apply/update"
```

---

### Task 8: Sync Screen with Live Output

**Files:**
- Create: `tui/screens/sync.py`

- [ ] **Step 1: Implement SyncScreen**

`tui/screens/sync.py`:
```python
"""Sync screen with live subprocess output."""

from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ProgressBar, RichLog, Static

from tui.core.config import TTConfig
from tui.core.system import SystemInfo


class SyncScreen(Screen):
    """Run sync operations with live output."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
    ]

    def __init__(
        self,
        tt_config: TTConfig,
        system: SystemInfo,
        mode: str = "full",
    ):
        super().__init__()
        self._tt_config = tt_config
        self._system = system
        self._mode = mode

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="sync-screen"):
            title_map = {
                "full": "Full System Sync",
                "files": "Files Only Sync",
                "snapshot": "Snapshot to ToolTamer",
            }
            yield Label(
                title_map.get(self._mode, "Sync"),
                classes="section-title",
            )
            yield RichLog(id="sync-log", wrap=True, highlight=True)
            with Container(id="sync-progress"):
                yield Static("[dim]Running...[/]", id="sync-status")
        yield Footer()

    def on_mount(self) -> None:
        self._run_sync()

    @work(thread=True)
    def _run_sync(self) -> None:
        import subprocess

        log = self.query_one("#sync-log", RichLog)
        status = self.query_one("#sync-status", Static)

        tt_script = self._tt_config.base.parent.parent / "toolTamer" / "bin" / "tt"
        # Try common locations for tt
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

        self.call_from_thread(
            log.write, f"[bold]Running:[/] tt {flag}\n"
        )

        try:
            proc = subprocess.Popen(
                ["bash", str(tt_script), flag],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env={
                    **__import__("os").environ,
                    "TERM": "dumb",
                },
            )
            for line in iter(proc.stdout.readline, ""):
                if not line:
                    break
                # Strip ANSI for clean display
                clean = line.rstrip()
                self.call_from_thread(log.write, clean)

            proc.wait()
            exit_code = proc.returncode
            if exit_code == 0:
                self.call_from_thread(
                    status.update,
                    "[green]Complete[/] — press ESC to return",
                )
            else:
                self.call_from_thread(
                    status.update,
                    f"[red]Failed[/] (exit {exit_code}) — press ESC to return",
                )

        except FileNotFoundError:
            self.call_from_thread(
                log.write,
                "[red]Error:[/] tt script not found. "
                "Make sure ~/toolTamer/bin/tt exists.",
            )
            self.call_from_thread(
                status.update, "[red]Error[/] — press ESC to return"
            )

    def action_go_back(self) -> None:
        self.app.pop_screen()
```

- [ ] **Step 2: Wire SyncScreen into dashboard**

In `tui/screens/dashboard.py`, update the sync cases in `action_menu_action`:

```python
        elif action == "sync_system":
            from tui.screens.sync import SyncScreen
            self.app.push_screen(
                SyncScreen(self._tt_config, self._system, mode="full")
            )
        elif action == "sync_files":
            from tui.screens.sync import SyncScreen
            self.app.push_screen(
                SyncScreen(self._tt_config, self._system, mode="files")
            )
        elif action == "snapshot":
            from tui.screens.sync import SyncScreen
            self.app.push_screen(
                SyncScreen(self._tt_config, self._system, mode="snapshot")
            )
```

- [ ] **Step 3: Manual smoke test**

Run: `cd ~/toolTamer && source .venv/bin/activate && python -m tui.app`

Press `F` (Files Only sync). Verify:
- Live output streams into the RichLog widget
- Status shows "Complete" or "Failed" when done
- `ESC` returns to dashboard

- [ ] **Step 4: Commit**

```bash
git add tui/screens/sync.py
git commit -m "feat: add sync screen with live subprocess output"
```

---

### Task 9: Integration & Polish

**Files:**
- Modify: `tui/app.py`
- Modify: `tui/screens/dashboard.py`
- Modify: `bin/tt-tui`

- [ ] **Step 1: Add `--help` and backward-compatible CLI args to tt-tui**

Update `bin/tt-tui`:
```python
#!/usr/bin/env python3
"""ToolTamer TUI entry point."""

import argparse
import sys
from pathlib import Path

# Add repo root to path so tui package is importable
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))


def main():
    parser = argparse.ArgumentParser(
        description="ToolTamer TUI — manage packages and config files"
    )
    parser.add_argument(
        "--base",
        default=str(Path.home() / ".config" / "toolTamer"),
        help="Path to ToolTamer config base directory",
    )
    parser.add_argument(
        "--classic",
        action="store_true",
        help="Use classic Bash TUI instead of Textual",
    )
    args = parser.parse_args()

    if args.classic:
        import subprocess
        tt_script = repo_root / "bin" / "tt"
        sys.exit(subprocess.call(["bash", str(tt_script)]))

    import os
    os.environ["TT_BASE"] = args.base

    from tui.app import ToolTamerApp
    app = ToolTamerApp()
    app.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Add screen install_screen mapping to app**

Update `tui/app.py` — register named screens:

```python
"""ToolTamer TUI - main application."""

import os
from pathlib import Path

from textual.app import App

from tui.core.config import TTConfig
from tui.core.system import SystemInfo
from tui.screens.dashboard import DashboardScreen


class ToolTamerApp(App):
    """ToolTamer terminal user interface."""

    TITLE = "ToolTamer"
    SUB_TITLE = "v2.0"
    CSS_PATH = "styles.tcss"

    def __init__(self):
        super().__init__()
        base = Path(os.environ.get(
            "TT_BASE", str(Path.home() / ".config" / "toolTamer")
        ))
        self._tt_config = TTConfig(base)
        self._system = SystemInfo()

    def on_mount(self) -> None:
        self.push_screen(
            DashboardScreen(self._tt_config, self._system)
        )


def main():
    app = ToolTamerApp()
    app.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Final integration test**

Run:
```bash
cd ~/toolTamer && source .venv/bin/activate
pytest tests/ -v
python -m tui.app
```

Expected: All tests pass. TUI launches with:
- Dashboard: host info, config tree, action menu
- `P` → Package Manager with table + info pane + move/copy
- `D` → File Manager with table + diff preview + apply/update
- `U`/`F`/`S` → Sync screens with live output
- `G` → suspends TUI, opens lazygit, resumes on exit
- `Q` → quit
- `ESC` → back from any screen

- [ ] **Step 4: Update AGENTS.md with Python development info**

Add Python section to `AGENTS.md`:
```markdown

## Python TUI (tui/)

- `tui/` contains the Textual-based TUI frontend; entry point is `bin/tt-tui` or `python -m tui.app`.
- Use Python 3.12+; dependencies managed via `pyproject.toml`; venv in `.venv/`.
- Run tests: `source .venv/bin/activate && pytest tests/ -v`
- Run TUI: `source .venv/bin/activate && python -m tui.app`
- Core logic lives in `tui/core/` (config reading, system detection); screens in `tui/screens/`.
- The classic Bash TUI remains available via `bin/tt` or `bin/tt-tui --classic`.
```

- [ ] **Step 5: Commit**

```bash
git add bin/tt-tui tui/ tests/ AGENTS.md
git commit -m "feat: integrate all screens, add CLI args, update AGENTS.md"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Project setup | `pyproject.toml`, init files, fixtures |
| 2 | Config module | `tui/core/config.py` + tests |
| 3 | System detection | `tui/core/system.py` + tests |
| 4 | CSS styles | `tui/styles.tcss` |
| 5 | Dashboard + App | `tui/app.py`, dashboard, widgets |
| 6 | Package Manager | `tui/screens/packages.py`, `_dest_picker.py` |
| 7 | File Manager | `tui/screens/files.py` |
| 8 | Sync Screen | `tui/screens/sync.py` |
| 9 | Integration | CLI args, wiring, AGENTS.md |
