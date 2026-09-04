"""Tests for checkIncludes() in bin/include.sh.

An includes.conf entry without a config dir is silently dropped by the
sync loops (`for i in common $(<includes.conf) $HOST` just iterates the
names), so the host quietly gets fewer packages and files. checkIncludes
runs once at startup and says so.
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INCLUDE = REPO_ROOT / "bin" / "include.sh"


def run(base: Path, host: str) -> subprocess.CompletedProcess:
    script = f"""
    source "{INCLUDE}"
    trap - EXIT
    BASE="{base}/"
    HOST="{host}"
    checkIncludes
    """
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)


@pytest.fixture
def base(tmp_path: Path) -> Path:
    b = tmp_path / "base"
    for cfg in ("common", "macosx", "host"):
        (b / "configs" / cfg).mkdir(parents=True)
    return b


def test_silent_when_all_includes_exist(base: Path):
    (base / "configs" / "host" / "includes.conf").write_text("macosx\n")
    r = run(base, "host")
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_warns_about_each_dangling_include(base: Path):
    (base / "configs" / "host" / "includes.conf").write_text("macosx\ngone\n# comment\nalso-gone\n")
    r = run(base, "host")
    assert r.returncode == 0  # a warning, not a failure: the run continues
    assert "gone" in r.stdout and "also-gone" in r.stdout
    assert "macosx" not in r.stdout
    assert "comment" not in r.stdout


def test_no_includes_file_is_fine(base: Path):
    r = run(base, "host")
    assert r.returncode == 0
    assert r.stdout.strip() == ""
