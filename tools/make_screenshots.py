#!/usr/bin/env python3
"""Generate the TUI screenshots used in the documentation.

Run it to refresh them after a UI change:

    source .venv/bin/activate && python tools/make_screenshots.py

Screenshots are written to docs/img/ as SVG — Textual renders its own
screens, so the result is real text (sharp at any size, selectable,
~50 KB) rather than a bitmap.

Everything is driven through Textual's test pilot against a synthetic
config with a mocked SystemInfo, so this needs no real ToolTamer setup,
touches nothing on the machine running it, and produces the same images
every time. That reproducibility is the point: screenshots that can be
regenerated on demand don't quietly drift out of date the way
hand-captured ones do.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "docs" / "img"
TERMINAL_SIZE = (110, 32)
HOSTNAME = "demo-mac"


def build_demo_config() -> Path:
    """A config that shows every package state at once: installed (OK),
    missing (!!), installed-but-untracked (++), dependency (D), and a
    tap-qualified entry."""
    base = Path(tempfile.mkdtemp(prefix="tt-screenshots-")) / "toolTamer"

    common = base / "configs" / "common"
    (common / "files").mkdir(parents=True)
    (common / "to_install.brew").write_text(
        "\n".join([
            "git",
            "ripgrep",
            "fzf",
            "neovim",          # not installed -> !!
            "bat",
            "forketyfork/tap/clawtunes",   # tap-qualified, installed as "clawtunes"
        ]) + "\n"
    )
    (common / "files.conf").write_text(
        "zshrc:.zshrc\nstarship.toml:.config/starship.toml\n"
    )
    (common / "files" / "zshrc").write_text(
        "export EDITOR=nvim\nexport PATH=$HOME/bin:$PATH\n"
    )
    (common / "files" / "starship.toml").write_text("[character]\nsymbol = '> '\n")

    host = base / "configs" / HOSTNAME
    (host / "files").mkdir(parents=True)
    (host / "to_install.brew").write_text("jq\nhtop\n")
    (host / "files.conf").write_text("kitty.conf:.config/kitty/kitty.conf\n")
    (host / "files" / "kitty.conf").write_text("font_size 14\n")
    (host / "includes.conf").write_text("")
    (host / "taps").write_text("forketyfork/tap\n")

    (base / "tt.conf").write_text("GIT_AUTO_UPDATE=ask\n")
    return base


def install_fakes() -> None:
    """Replace every SystemInfo call that would shell out, so the images
    show the same fixed system regardless of the machine used."""
    from tui.core.system import SystemInfo

    installed = [
        "git", "ripgrep", "fzf", "bat", "jq", "htop",
        "clawtunes",        # the tap package, listed under its short name
        "curl", "openssl@3", "readline",   # dependencies
        "wget",             # installed, in no config -> ++
    ]
    deps = {"curl", "openssl@3", "readline"}
    required_by = {
        "openssl@3": ["curl", "git"],
        "readline": ["bat", "htop"],
        "curl": ["git"],
    }

    SystemInfo.list_installed_packages = lambda self: list(installed)
    SystemInfo.list_dependency_packages = lambda self: set(deps)
    SystemInfo.get_required_by = lambda self, pkg: required_by.get(pkg, [])
    SystemInfo.get_package_tap = lambda self, pkg: (
        "forketyfork/tap" if "clawtunes" in pkg else None
    )
    SystemInfo.get_package_info = lambda self, pkg: (
        f"==> {pkg}\nA demo package used for the documentation screenshots.\n"
        f"https://example.com/{pkg.rsplit('/', 1)[-1]}\n"
    )
    SystemInfo.list_package_full_names = lambda self: {
        "clawtunes": "forketyfork/tap/clawtunes"
    }


async def capture() -> list[str]:
    from tui.app import ToolTamerApp

    written: list[str] = []
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    def shot(app, name: str) -> None:
        path = OUT_DIR / f"{name}.svg"
        app.save_screenshot(str(path))
        written.append(f"{path.relative_to(REPO_ROOT)}")

    with patch("socket.gethostname", return_value=HOSTNAME):
        app = ToolTamerApp()
        async with app.run_test(size=TERMINAL_SIZE) as pilot:
            await pilot.pause()
            shot(app, "dashboard")

            # Trigger the menu actions directly rather than pressing Enter
            # on a list position: the entries are ordered by usefulness,
            # not by what is safe to screenshot (the first one starts a
            # real sync and suspends the app), and a reordering would
            # silently capture the wrong screen.
            for action, name, settle in (
                ("packages", "packages", 0.6),
                ("files", "files", 0.4),
            ):
                app.screen.action_menu_action(action)
                await pilot.pause()
                # Let background workers finish, so e.g. the dependency
                # column is filled in rather than caught mid-scan.
                await asyncio.sleep(settle)
                await pilot.pause()
                shot(app, name)
                await pilot.press("escape")
                await pilot.pause()

    return written


def main() -> int:
    base = build_demo_config()
    os.environ["TT_BASE"] = str(base)
    install_fakes()
    written = asyncio.run(capture())
    for path in written:
        print(f"wrote {path}")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
