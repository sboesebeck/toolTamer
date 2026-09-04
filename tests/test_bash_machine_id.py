"""Tests for readMachineId / resolveHost / writeMachineId in bin/include.sh.

The Python side (tui/core/machine_id.py) reads the same file, so the parse
rule — first line, trimmed, empty means unset — is pinned on both sides;
a drift between them would make bin/tt and the TUI use different host
configs on the same machine. include.sh can be sourced directly (it only
defines functions and sets BASE, which the test overrides afterwards).
"""

import socket
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INCLUDE = REPO_ROOT / "bin" / "include.sh"


def run(base: Path, body: str) -> str:
    script = f"""
    source "{INCLUDE}"
    trap - EXIT  # include.sh installs a cleanup trap that prints on exit
    BASE="{base}/"
    {body}
    """
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture
def base(tmp_path: Path) -> Path:
    b = tmp_path / "base"
    b.mkdir()
    return b


def test_resolve_host_falls_back_to_hostname(base: Path):
    assert run(base, "resolveHost") == socket.gethostname()


@pytest.mark.parametrize("content", ["", "  \n\t\n"])
def test_blank_machine_id_means_unset(base: Path, content: str):
    (base / "machine-id").write_text(content)
    assert run(base, "readMachineId") == ""
    assert run(base, "resolveHost") == socket.gethostname()


def test_machine_id_is_first_line_trimmed(base: Path):
    (base / "machine-id").write_text("  gandalf.home.local \t\nignored\n")
    assert run(base, "resolveHost") == "gandalf.home.local"


def test_write_pins_and_ignores_once_in_a_repo(base: Path):
    (base / ".git").mkdir()
    (base / ".gitignore").write_text("cache/\n")
    run(base, 'writeMachineId pinned; writeMachineId pinned2')
    assert (base / "machine-id").read_text() == "pinned2\n"
    lines = (base / ".gitignore").read_text().splitlines()
    assert lines.count("machine-id") == 1
    assert "cache/" in lines


def test_write_without_repo_leaves_gitignore_alone(base: Path):
    run(base, "writeMachineId x")
    assert (base / "machine-id").read_text() == "x\n"
    assert not (base / ".gitignore").exists()
