import platform
import subprocess
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
    pkgs = info.list_installed_packages()
    assert isinstance(pkgs, list)


def test_list_dependency_packages_brew(monkeypatch):
    system = SystemInfo()
    system.installer = "brew"
    seen_cmds = []

    def fake_run(cmd, **kwargs):
        seen_cmds.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="openssl@3\nreadline\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = system.list_dependency_packages()

    assert result == {"openssl@3", "readline"}
    assert seen_cmds == [["brew", "list", "--no-installed-on-request"]]


def test_list_dependency_packages_apt(monkeypatch):
    system = SystemInfo()
    system.installer = "apt"

    def fake_run(cmd, **kwargs):
        assert cmd == ["apt-mark", "showauto"]
        return subprocess.CompletedProcess(cmd, 0, stdout="libssl3\nlibcurl4\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert system.list_dependency_packages() == {"libssl3", "libcurl4"}


def test_list_dependency_packages_pacman(monkeypatch):
    system = SystemInfo()
    system.installer = "pacman"

    def fake_run(cmd, **kwargs):
        assert cmd == ["pacman", "-Qdq"]
        return subprocess.CompletedProcess(cmd, 0, stdout="glibc\nzlib\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert system.list_dependency_packages() == {"glibc", "zlib"}


def test_list_dependency_packages_unknown_installer_no_subprocess_call(monkeypatch):
    system = SystemInfo()
    system.installer = "unknown"

    def fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called for an unknown installer")

    monkeypatch.setattr(subprocess, "run", fail_if_called)

    assert system.list_dependency_packages() == set()


def test_list_dependency_packages_missing_binary_returns_empty_set(monkeypatch):
    system = SystemInfo()
    system.installer = "brew"

    def missing(*args, **kwargs):
        raise FileNotFoundError("brew not on PATH")

    monkeypatch.setattr(subprocess, "run", missing)

    assert system.list_dependency_packages() == set()


def test_list_dependency_packages_timeout_returns_empty_set(monkeypatch):
    system = SystemInfo()
    system.installer = "brew"

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["brew"], timeout=30)

    monkeypatch.setattr(subprocess, "run", timeout)

    assert system.list_dependency_packages() == set()


def test_list_dependency_packages_empty_stdout_returns_empty_set(monkeypatch):
    system = SystemInfo()
    system.installer = "brew"

    def empty(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", empty)

    assert system.list_dependency_packages() == set()
