from pathlib import Path
import pytest


@pytest.fixture(autouse=True)
def _never_touch_the_real_config(tmp_path: Path, monkeypatch):
    """Point TT_BASE at a throwaway dir for every test.

    Anything deriving a path from TT_BASE (currently the dependency cache
    in tui/core/dep_cache.py) would otherwise fall back to the real
    ~/.config/toolTamer — a test run then writes fake data into the
    user's actual cache and results bleed between tests. Tests that need
    a populated config still override TT_BASE with their own tmp_config;
    this only guarantees the default is never the real thing.
    """
    monkeypatch.setenv("TT_BASE", str(tmp_path / "tt-base-guard"))


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
