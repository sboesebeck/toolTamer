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
