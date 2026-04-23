"""Read and manipulate ToolTamer configuration hierarchy."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileMapping:
    """A single file mapping entry from files.conf."""
    stored: str
    target: str
    config: str
    repo_path: Path


class TTConfig:
    """Interface to the ToolTamer config directory."""

    def __init__(self, base: Path):
        self.base = Path(base)
        self.configs_dir = self.base / "configs"

    def list_configs(self) -> list[str]:
        if not self.configs_dir.exists():
            return []
        return sorted(
            d.name for d in self.configs_dir.iterdir()
            if d.is_dir() and not d.is_symlink()
        )

    def get_includes(self, config: str) -> list[str]:
        inc_file = self.configs_dir / config / "includes.conf"
        if not inc_file.exists():
            return []
        return [
            line.strip() for line in inc_file.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def resolve_chain(self, config: str) -> list[str]:
        chain = ["common"]
        for inc in self.get_includes(config):
            if inc not in chain:
                chain.append(inc)
        if config not in chain:
            chain.append(config)
        return chain

    def get_parents(self, config: str) -> list[str]:
        if config == "common":
            return []
        parents = ["common"]
        for inc in self.get_includes(config):
            if inc not in parents:
                parents.append(inc)
        return parents

    def get_children(self, config: str) -> list[str]:
        children = []
        for cfg in self.list_configs():
            if cfg == config:
                continue
            if config in self.get_includes(cfg):
                children.append(cfg)
        return children

    def get_packages(self, config: str, installer: str) -> list[str]:
        pkg_file = self.configs_dir / config / f"to_install.{installer}"
        if not pkg_file.exists():
            return []
        return [
            line.strip() for line in pkg_file.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def get_effective_packages(self, config: str, installer: str) -> list[str]:
        seen = set()
        result = []
        for cfg in self.resolve_chain(config):
            for pkg in self.get_packages(cfg, installer):
                if pkg not in seen:
                    seen.add(pkg)
                    result.append(pkg)
        return result

    def get_file_mappings(self, config: str) -> list[tuple[str, str]]:
        conf_file = self.configs_dir / config / "files.conf"
        if not conf_file.exists():
            return []
        mappings = []
        for line in conf_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ";" not in line:
                continue
            stored, target = line.split(";", 1)
            stored, target = stored.strip(), target.strip()
            if stored and target:
                mappings.append((stored, target))
        return mappings

    def get_effective_file_mappings(self, config: str) -> list[FileMapping]:
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
        taps_file = self.configs_dir / config / "taps"
        if not taps_file.exists():
            return []
        return [
            line.strip() for line in taps_file.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def get_effective_taps(self, config: str) -> list[str]:
        """Get all taps across the include chain, deduplicated."""
        seen: set[str] = set()
        result: list[str] = []
        for cfg in self.resolve_chain(config):
            for tap in self.get_taps(cfg):
                if tap not in seen:
                    seen.add(tap)
                    result.append(tap)
        return result

    def _remove_tap(self, config: str, tap: str) -> None:
        """Remove a tap from a config's taps file."""
        taps_file = self.configs_dir / config / "taps"
        if not taps_file.exists():
            return
        lines = taps_file.read_text().splitlines()
        filtered = [l for l in lines if l.strip() != tap]
        taps_file.write_text("\n".join(filtered) + "\n" if filtered else "")

    def add_tap(self, config: str, tap: str) -> bool:
        """Add a brew tap to a config's taps file. Returns True if added."""
        taps_file = self.configs_dir / config / "taps"
        existing = self.get_taps(config)
        if tap in existing:
            return False
        with taps_file.open("a") as f:
            f.write(f"{tap}\n")
        return True

    def move_package(self, source: str, dest: str, package: str, installer: str) -> None:
        self._remove_package(source, package, installer)
        self._add_package(dest, package, installer)

    def copy_package(self, source: str, dest: str, package: str, installer: str) -> None:
        self._add_package(dest, package, installer)

    def _add_package(self, config: str, package: str, installer: str) -> None:
        pkg_file = self.configs_dir / config / f"to_install.{installer}"
        if package not in self.get_packages(config, installer):
            with pkg_file.open("a") as f:
                f.write(f"{package}\n")

    def _remove_package(self, config: str, package: str, installer: str) -> None:
        pkg_file = self.configs_dir / config / f"to_install.{installer}"
        if not pkg_file.exists():
            return
        lines = pkg_file.read_text().splitlines()
        filtered = [line for line in lines if line.strip() != package]
        pkg_file.write_text("\n".join(filtered) + "\n" if filtered else "")
