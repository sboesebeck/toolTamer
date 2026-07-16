from pathlib import Path

import pytest
from rich.text import Text
from textual.app import App
from textual.widgets import OptionList

from tui.screens.files import SaveChoiceScreen


class _DialogApp(App):
    """Minimal host app to mount a modal screen under test."""

    def __init__(self, screen):
        super().__init__()
        self._screen_under_test = screen

    def on_mount(self) -> None:
        self.push_screen(self._screen_under_test)


def _visible_prompt(option) -> Text:
    prompt = option.prompt
    return prompt if isinstance(prompt, Text) else Text.from_markup(prompt)


def _assert_option_visible(option, key_hint: str) -> None:
    rendered = _visible_prompt(option)
    # The key hint like "[c]" must survive into the visible text — Rich
    # markup would swallow it as a style tag ("c" even means conceal,
    # rendering the whole option invisible).
    assert f"[{key_hint}]" in rendered.plain, (
        f"key hint [{key_hint}] missing from rendered option: {rendered.plain!r}"
    )
    assert not any(span.style == "conceal" for span in rendered.spans), (
        f"option for [{key_hint}] is rendered concealed (invisible)"
    )


@pytest.mark.asyncio
async def test_save_choice_options_visible_when_system_file_missing():
    """Inherited entry whose system file is missing: the dialog offers only
    the 'copy parent version' option — it must be visible, not concealed."""
    screen = SaveChoiceScreen(
        "macosx", "myhost", ".config/foo/bar",
        system_exists=False, repo_exists=True,
    )
    app = _DialogApp(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        ol = screen.query_one(OptionList)
        assert ol.option_count == 1
        _assert_option_visible(ol.get_option_at_index(0), "c")


@pytest.mark.asyncio
async def test_save_choice_options_visible_when_both_exist():
    screen = SaveChoiceScreen(
        "common", "myhost", ".zshrc",
        system_exists=True, repo_exists=True,
    )
    app = _DialogApp(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        ol = screen.query_one(OptionList)
        assert ol.option_count == 3
        _assert_option_visible(ol.get_option_at_index(0), "a")
        _assert_option_visible(ol.get_option_at_index(1), "l")
        _assert_option_visible(ol.get_option_at_index(2), "c")
