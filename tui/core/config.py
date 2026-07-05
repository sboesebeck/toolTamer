"""Read and manipulate ToolTamer configuration hierarchy."""

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


def _resolve_effective_target(stored: str, target: str) -> str:
    """Mirror include.sh's target resolution: when target ends with '/', the
    final destination is target + basename(stored)."""
    if target.endswith("/"):
        return target + PurePosixPath(stored).name
    return target


def _path_within(child: str, parent: str) -> bool:
    """True when the relative path `child` lies strictly inside `parent`."""
    return child != parent and child.startswith(parent.rstrip("/") + "/")


def iter_tree_files(root: Path):
    """Yield (relative_posix_path, path) for every file and symlink under
    root. Symlinks (including symlinked directories) are treated as leaf
    entries and never followed."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        for name in filenames:
            p = base / name
            yield p.relative_to(root).as_posix(), p
        for name in list(dirnames):
            p = base / name
            if p.is_symlink():
                dirnames.remove(name)
                yield p.relative_to(root).as_posix(), p


def _entry_fingerprint(path: Path) -> str:
    if path.is_symlink():
        return "link:" + os.readlink(path)
    h = hashlib.sha1()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except (OSError, PermissionError):
        return "unreadable"
    return h.hexdigest()


def tree_signature(root: Path) -> str:
    """Cheap stat-based fingerprint of a directory tree (no content reads).
    Useful as a cache key: if unchanged, the tree_hash is unchanged too."""
    sig = hashlib.sha1()
    for rel, p in sorted(iter_tree_files(root)):
        try:
            st = p.lstat()
        except OSError:
            continue
        sig.update(f"{rel}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return sig.hexdigest()


def tree_hash(root: Path) -> str:
    """Content hash over all files/symlinks (path + content) of a tree."""
    h = hashlib.sha1()
    for rel, p in sorted(iter_tree_files(root)):
        h.update(f"{_entry_fingerprint(p)}  {rel}\n".encode())
    return h.hexdigest()


def dir_diff(source: Path, dest: Path) -> tuple[list[str], list[str], list[str]]:
    """Compare two trees. Returns (only_in_source, only_in_dest, changed),
    each a sorted list of relative paths."""
    src = {rel: p for rel, p in iter_tree_files(source)} if source.is_dir() else {}
    dst = {rel: p for rel, p in iter_tree_files(dest)} if dest.is_dir() else {}
    only_src = sorted(set(src) - set(dst))
    only_dst = sorted(set(dst) - set(src))
    changed = sorted(
        rel for rel in set(src) & set(dst)
        if _entry_fingerprint(src[rel]) != _entry_fingerprint(dst[rel])
    )
    return only_src, only_dst, changed


@dataclass
class FileMapping:
    """A single file mapping entry from files.conf."""
    stored: str
    target: str
    config: str
    repo_path: Path
    is_effective: bool = True
    shadowed_by: str | None = None

    @property
    def effective_target(self) -> str:
        return _resolve_effective_target(self.stored, self.target)


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
            if not line or line.startswith("#"):
                continue
            if ";" in line:
                stored, target = line.split(";", 1)
                stored, target = stored.strip(), target.strip()
            else:
                # include.sh's `cut -f2 -d\;` returns the whole line when no
                # delimiter is present, so bash syncs these as stored=target.
                stored = target = line
            if stored and target:
                mappings.append((stored, target))
        return mappings

    def get_effective_file_mappings(self, config: str) -> list[FileMapping]:
        """Return all file mappings across the include chain.

        When the same target is mapped from multiple configs, the deepest
        in the chain wins (is_effective=True); the others are kept in the
        result with is_effective=False and shadowed_by set, so callers can
        surface duplicates instead of silently hiding them.
        """
        chain = self.resolve_chain(config)
        # include.sh's createEffectiveFilesList does last-write-wins by
        # effective target across the full chain, so iterate everything
        # in chain order and let the last occurrence win — including
        # duplicates within a single config.
        winner: dict[str, tuple[str, str]] = {}
        for cfg in chain:
            for stored, target in self.get_file_mappings(cfg):
                winner[_resolve_effective_target(stored, target)] = (cfg, stored)

        result: list[FileMapping] = []
        for cfg in chain:
            for stored, target in self.get_file_mappings(cfg):
                eff = _resolve_effective_target(stored, target)
                win_cfg, win_stored = winner[eff]
                is_effective = cfg == win_cfg and stored == win_stored
                result.append(FileMapping(
                    stored=stored,
                    target=target,
                    config=cfg,
                    repo_path=self.configs_dir / cfg / "files" / stored,
                    is_effective=is_effective,
                    shadowed_by=None if is_effective else win_cfg,
                ))
        return result

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

    def add_file_mapping(self, config: str, stored: str, target: str) -> None:
        """Add a file mapping to a config's files.conf."""
        conf_file = self.configs_dir / config / "files.conf"
        if not conf_file.exists():
            conf_file.write_text("")
        # Check if already present
        for s, t in self.get_file_mappings(config):
            if s == stored and t == target:
                return
        with conf_file.open("a") as f:
            f.write(f"{stored};{target}\n")

    def remove_file_mapping(self, config: str, stored: str, target: str) -> None:
        """Remove a file mapping from a config's files.conf."""
        conf_file = self.configs_dir / config / "files.conf"
        if not conf_file.exists():
            return
        lines = conf_file.read_text().splitlines()
        filtered = []
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith("#"):
                filtered.append(line)
                continue
            if ";" in line_stripped:
                s, t = line_stripped.split(";", 1)
                s, t = s.strip(), t.strip()
            else:
                s = t = line_stripped
            if s == stored and t == target:
                continue
            filtered.append(line)
        conf_file.write_text("\n".join(filtered) + "\n" if filtered else "")

    def find_covering_dir(self, rel: str, configs) -> FileMapping | None:
        """Find a tracked directory entry whose effective target contains
        `rel`. Searches the given config names; the deepest (longest) match
        wins. Returns None when no tracked directory covers the path."""
        best: FileMapping | None = None
        for cfg in configs:
            for stored, target in self.get_file_mappings(cfg):
                repo = self.configs_dir / cfg / "files" / stored
                if not repo.is_dir() or repo.is_symlink():
                    continue
                eff = _resolve_effective_target(stored, target)
                if _path_within(rel, eff):
                    if best is None or len(eff) > len(best.effective_target):
                        best = FileMapping(stored, target, cfg, repo)
        return best

    def add_path(
        self,
        dest_config: str,
        source: Path,
        chain_config: str | None = None,
        home: Path | None = None,
    ) -> list[str]:
        """Add a file or directory under $HOME to a config.

        - A file inside an already-tracked directory is not added as a new
          entry; instead the copy inside that directory snapshot is updated.
        - Adding a directory snapshots the whole tree and absorbs entries of
          the destination config whose target lies inside the directory.
        Returns a human-readable report of what happened."""
        home = home or Path.home()
        rel = source.relative_to(home).as_posix()
        report: list[str] = []
        scope = list(dict.fromkeys(self.resolve_chain(chain_config or dest_config) + [dest_config]))

        if source.is_dir() and not source.is_symlink():
            dest_target = self.configs_dir / dest_config / "files" / rel
            dest_target.parent.mkdir(parents=True, exist_ok=True)
            if dest_target.is_dir() and not dest_target.is_symlink():
                shutil.rmtree(dest_target)
            elif dest_target.exists() or dest_target.is_symlink():
                dest_target.unlink()
            shutil.copytree(source, dest_target, symlinks=True)
            self.add_file_mapping(dest_config, rel, rel)
            report.append(f"Added directory ~/{rel} to '{dest_config}'")
            report += self._absorb_into_dir(dest_config, rel, rel)
            for cfg in scope:
                if cfg == dest_config:
                    continue
                for stored, target in self.get_file_mappings(cfg):
                    eff = _resolve_effective_target(stored, target)
                    if _path_within(eff, rel):
                        report.append(
                            f"WARNING: ~/{eff} is also mapped in '{cfg}' — it now conflicts "
                            f"with directory ~/{rel}; consider removing it there"
                        )
            return report

        # Regular file
        covering = self.find_covering_dir(rel, scope)
        if covering is not None:
            inner = rel[len(covering.effective_target.rstrip("/")) + 1:]
            snap_file = covering.repo_path / inner
            if snap_file.is_file() and snap_file.read_bytes() == source.read_bytes():
                report.append(
                    f"~/{rel} is already covered by directory ~/{covering.effective_target} "
                    f"('{covering.config}') and up to date — nothing to add"
                )
            else:
                snap_file.parent.mkdir(parents=True, exist_ok=True)
                snap_file.write_bytes(source.read_bytes())
                shutil.copystat(source, snap_file, follow_symlinks=False)
                report.append(
                    f"~/{rel} lies inside tracked directory ~/{covering.effective_target} "
                    f"('{covering.config}') — updated the directory snapshot, no new entry"
                )
            return report

        dest_target = self.configs_dir / dest_config / "files" / rel
        dest_target.parent.mkdir(parents=True, exist_ok=True)
        existed = dest_target.exists()
        dest_target.write_bytes(source.read_bytes())
        self.add_file_mapping(dest_config, rel, rel)
        report.append(f"{'Updated' if existed else 'Added'} ~/{rel} in '{dest_config}'")
        return report

    def _absorb_into_dir(self, config: str, dir_stored: str, dir_eff: str) -> list[str]:
        """Remove entries of `config` whose effective target lies inside the
        tracked directory `dir_eff`. Stored copies that live outside any
        remaining tracked directory snapshot are deleted."""
        report: list[str] = []
        for stored, target in list(self.get_file_mappings(config)):
            eff = _resolve_effective_target(stored, target)
            if stored == dir_stored and eff == dir_eff:
                continue  # the directory entry itself
            if not _path_within(eff, dir_eff):
                continue
            self.remove_file_mapping(config, stored, target)
            if self._delete_stored_if_unreferenced(config, stored):
                report.append(f"Absorbed ~/{eff} into ~/{dir_eff} (entry + stored copy '{stored}' removed)")
            else:
                report.append(f"Absorbed ~/{eff} into ~/{dir_eff} (entry removed)")
        return report

    def _delete_stored_if_unreferenced(self, config: str, stored: str) -> bool:
        """Delete files/<stored> unless it is still referenced by another
        mapping or lives inside a tracked directory snapshot. Prunes empty
        parent directories afterwards. Returns True when deleted."""
        files_root = self.configs_dir / config / "files"
        repo_path = files_root / stored
        if not repo_path.exists() and not repo_path.is_symlink():
            return False
        for s, _t in self.get_file_mappings(config):
            if s == stored:
                return False
            other = files_root / s
            if other.is_dir() and not other.is_symlink() and _path_within(stored, s):
                return False
        if repo_path.is_dir() and not repo_path.is_symlink():
            shutil.rmtree(repo_path)
        else:
            repo_path.unlink()
        parent = repo_path.parent
        while parent != files_root and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
        return True

    def absorb_redundant_entries(self, config: str, delete_orphans: bool = False) -> list[str]:
        """Clean up a config: entries nested inside tracked directories are
        absorbed (the directory snapshot is the single source of truth).
        With delete_orphans, stored files no longer referenced by any
        mapping are removed as well. Returns a report."""
        report: list[str] = []
        files_root = self.configs_dir / config / "files"
        mappings = self.get_file_mappings(config)

        dir_entries = []
        for stored, target in mappings:
            repo = files_root / stored
            if repo.is_dir() and not repo.is_symlink():
                dir_entries.append((stored, _resolve_effective_target(stored, target)))
        # Only outermost directories absorb; nested tracked dirs are absorbed themselves.
        outer = [
            (stored, eff) for stored, eff in dir_entries
            if not any(_path_within(eff, other_eff) for _s, other_eff in dir_entries if other_eff != eff)
        ]
        for stored, eff in outer:
            report += self._absorb_into_dir(config, stored, eff)

        # Report broken lines (empty stored part like ";.vimrc") — bash skips them too.
        conf_file = self.configs_dir / config / "files.conf"
        if conf_file.exists():
            for line in conf_file.read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith(";"):
                    report.append(f"WARNING: broken entry '{stripped}' (empty stored name, never synced)")

        if delete_orphans and files_root.is_dir():
            remaining = self.get_file_mappings(config)
            referenced_files = {s for s, _t in remaining}
            referenced_dirs = [
                s for s in referenced_files
                if (files_root / s).is_dir() and not (files_root / s).is_symlink()
            ]
            for rel, path in sorted(iter_tree_files(files_root)):
                if rel in referenced_files:
                    continue
                if any(_path_within(rel, d) for d in referenced_dirs):
                    continue
                path.unlink()
                report.append(f"Removed orphaned stored file '{rel}' (not referenced by files.conf)")
                parent = path.parent
                while parent != files_root and parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
        return report

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
