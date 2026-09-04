"""Stable identity of this machine, independent of what `hostname` says.

The hostname changes with the network (VPN, DHCP domain, mDNS suffix), so
`$BASE/machine-id` pins which host config this machine uses. bin/tt writes
the file; the Python side only reads it. Keep the parsing rule in sync with
resolveHost() in bin/include.sh: first line, whitespace trimmed, empty means
"not set".
"""

from pathlib import Path

MACHINE_ID_FILE = "machine-id"


def machine_id_path(base: Path) -> Path:
    return Path(base) / MACHINE_ID_FILE


def read_machine_id(base: Path) -> str | None:
    """Return the configured machine id, or None when unset/missing."""
    path = machine_id_path(base)
    try:
        first_line = path.read_text().splitlines()[0]
    except (OSError, IndexError):
        return None
    return first_line.strip() or None


def write_machine_id(base: Path, name: str) -> None:
    """Pin `name` as this machine's id — the Python twin of writeMachineId()
    in bin/include.sh.

    The base dir is a git repo shared by every machine, so the id is added
    to its .gitignore the first time (like cache/) instead of ending up
    committed from one machine and applied to all of them.
    """
    base = Path(base)
    machine_id_path(base).write_text(f"{name}\n")
    if not (base / ".git").exists():
        return
    gitignore = base / ".gitignore"
    existing = gitignore.read_text() if gitignore.exists() else ""
    if MACHINE_ID_FILE in existing.splitlines():
        return
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    with gitignore.open("a") as fh:
        fh.write(
            f"{prefix}# Which host config this machine uses (machine-specific)\n"
            f"{MACHINE_ID_FILE}\n"
        )
