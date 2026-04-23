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
    pkgs = info.list_installed_packages()
    assert isinstance(pkgs, list)
