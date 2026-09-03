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


from tui.screens.files import FileScreen


@pytest.mark.parametrize("state,token", [
    ("ok", "OK"),
    ("ahead", "OK"),
    ("behind", "!!"),
    ("dirty", "!!"),
    ("diverged", "!!"),
    ("missing", "--"),
    ("not_a_repo", "??"),
    ("wrong_origin", "??"),
    ("invalid_spec", "??"),
])
def test_repo_status_token_mapping(state: str, token: str):
    assert FileScreen._repo_status_token(state) == token


from tui.core.repo import RepoSpec


def test_repo_detail_lines_report_missing_clone(tmp_path: Path):
    lines = FileScreen._repo_detail_lines(
        RepoSpec(url="git@example.com:me/r.git", branch="main"), tmp_path / "nope"
    )
    text = "\n".join(t for t, _ in lines)
    assert "git@example.com:me/r.git" in text
    assert "main" in text
    assert "not cloned yet" in text.lower()


def test_repo_detail_lines_flag_invalid_spec(tmp_path: Path):
    lines = FileScreen._repo_detail_lines(RepoSpec(url=""), tmp_path)
    text = "\n".join(t for t, _ in lines)
    assert "no url" in text


import subprocess
from unittest.mock import patch

from textual.widgets import DataTable, RichLog

from tui.core import repo as repo_mod
from tui.core.config import TTConfig
from tui.core.repo import write_marker
from tui.core.system import SystemInfo


def _run_git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_origin_repo(path: Path) -> Path:
    """A local-path git repo used as 'the remote' — never a network URL,
    so repo.status() (fetch=False) never touches the network."""
    path.mkdir(parents=True)
    _run_git(path, "init", "--quiet", "--initial-branch=main")
    _run_git(path, "config", "user.email", "t@example.com")
    _run_git(path, "config", "user.name", "Test")
    (path / "README.md").write_text("hello\n")
    _run_git(path, "add", "README.md")
    _run_git(path, "commit", "--quiet", "-m", "init")
    return path


def _build_repo_entry_config(tmp_path: Path) -> tuple[Path, Path]:
    """A tmp_config with one repo-tracked entry ('myrepo' -> '~/.myrepo'),
    plus a fake $HOME that already holds a real local clone of that
    entry's origin, so repo.status() reports 'ok' without any network
    access."""
    base = tmp_path / "toolTamer"
    configs = base / "configs"
    common = configs / "common"
    common.mkdir(parents=True)
    (common / "files").mkdir()
    host = configs / "testhost"
    host.mkdir(parents=True)
    (host / "files").mkdir()
    (host / "files.conf").write_text("")
    (host / "includes.conf").write_text("")
    (base / "tt.conf").write_text("")

    origin = _make_origin_repo(tmp_path / "origin.git")

    store_dir = common / "files" / "myrepo"
    store_dir.mkdir()
    write_marker(store_dir, RepoSpec(url=str(origin), branch="main"))
    (common / "files.conf").write_text("myrepo;.myrepo\n")

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    clone_dir = fake_home / ".myrepo"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(clone_dir)],
        check=True, capture_output=True,
    )
    _run_git(clone_dir, "config", "user.email", "t@example.com")
    _run_git(clone_dir, "config", "user.name", "Test")

    return base, fake_home


class _RepoFileScreenHarness(App):
    """Minimal app whose only job is to host a FileScreen for the test."""

    def __init__(self, tt_config: TTConfig, system: SystemInfo):
        super().__init__()
        self._tt_config = tt_config
        self._system = system

    def on_mount(self) -> None:
        self.push_screen(FileScreen(self._tt_config, self._system))


def _extract_log_text(log) -> str:
    lines = []
    for strip in log.lines:
        lines.append("".join(segment.text for segment in strip))
    return "\n".join(lines)


@pytest.mark.asyncio
async def test_repo_entry_renders_status_token_and_branch_in_list(tmp_path: Path):
    base, fake_home = _build_repo_entry_config(tmp_path)
    with patch("socket.gethostname", return_value="testhost"), \
         patch.object(Path, "home", return_value=fake_home):
        app = _RepoFileScreenHarness(TTConfig(base), SystemInfo())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#file-table", DataTable)
            row = table.get_row("common:myrepo:.myrepo")

    st_text, target_text, _cfg_text = row
    assert st_text.plain == "OK"
    assert "⎇ main" in target_text.plain


@pytest.mark.asyncio
async def test_repo_entry_detail_pane_shows_repo_state_not_diff(tmp_path: Path):
    base, fake_home = _build_repo_entry_config(tmp_path)
    with patch("socket.gethostname", return_value="testhost"), \
         patch.object(Path, "home", return_value=fake_home):
        app = _RepoFileScreenHarness(TTConfig(base), SystemInfo())
        async with app.run_test() as pilot:
            screen = app.screen
            worker = screen._show_diff("common", "myrepo", ".myrepo")
            await worker.wait()
            await pilot.pause()
            text = _extract_log_text(screen.query_one("#file-diff", RichLog))

    assert "Tracked as git repository" in text
    assert "main" in text
    assert "Status: ok" in text
    assert "content differs" not in text
    assert "Directories" not in text


@pytest.mark.parametrize("broken_state", ["not_a_repo", "wrong_origin", "invalid_spec"])
@pytest.mark.asyncio
async def test_broken_repo_states_render_red_not_yellow(tmp_path: Path, monkeypatch, broken_state: str):
    """R14: not_a_repo / wrong_origin / invalid_spec must render the same
    red used for every other '??' row, not the bold-yellow used for a
    merely dirty/behind repo."""
    base, fake_home = _build_repo_entry_config(tmp_path)
    monkeypatch.setattr(repo_mod, "status", lambda *a, **k: broken_state)
    with patch("socket.gethostname", return_value="testhost"), \
         patch.object(Path, "home", return_value=fake_home):
        app = _RepoFileScreenHarness(TTConfig(base), SystemInfo())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#file-table", DataTable)
            row = table.get_row("common:myrepo:.myrepo")

    st_text = row[0]
    style = str(st_text.spans[0].style) if st_text.spans else ""
    assert "red" in style
    assert "yellow" not in style


def test_do_apply_never_deletes_a_repo_target(tmp_config: Path, tmp_path: Path, monkeypatch):
    """Regression: the directory branch of _do_apply used to rmtree the
    target unconditionally, which would wipe a tracked repo.

    Ruling R3: the origin is a local filesystem path, never git@.../ssh://...
    — sync_to_system's status(fetch=True) runs a real `git fetch`, and a
    real remote URL would attempt a network connection."""
    home = tmp_path / "home"
    target = home / ".config" / "nvim"
    target.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", "--initial-branch=main"],
                   cwd=target, check=True, capture_output=True)
    origin = str(tmp_path / "no-such-origin.git")
    subprocess.run(["git", "remote", "add", "origin", origin],
                   cwd=target, check=True, capture_output=True)
    (target / "work_in_progress.lua").write_text("-- precious\n")

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("nvim;.config/nvim\n")
    store = host / "files" / "nvim"
    store.mkdir(parents=True)
    (store / ".ttgit").write_text(f"url = {origin}\nbranch = main\n")

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    screen = FileScreen.__new__(FileScreen)
    screen._tt_config = TTConfig(tmp_config)
    screen._tree_cache = {}
    screen._refresh_files = lambda: None
    screen._show_diff = lambda *a, **k: None
    screen.notify = lambda *a, **k: None

    screen._do_apply("testhost", "nvim", ".config/nvim")

    assert (target / "work_in_progress.lua").read_text() == "-- precious\n"
    assert (target / ".git").exists()


from tui.core.repo import read_marker


def test_save_repo_marker_picks_up_new_origin(tmp_config: Path, tmp_path: Path, monkeypatch):
    """Ruling R3: local filesystem paths stand in for both the old and new
    origin — never git@.../ssh://... — so detect()'s `git remote get-url`
    stays fully offline."""
    home = tmp_path / "home"
    target = home / ".config" / "nvim"
    target.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", "--initial-branch=develop"],
                   cwd=target, check=True, capture_output=True)
    _run_git(target, "config", "user.email", "t@example.com")
    _run_git(target, "config", "user.name", "Test")
    # detect() asks `git rev-parse --abbrev-ref HEAD`, which fails on an
    # unborn branch — an empty repo has no established branch to report.
    # A real tracked repo always has at least one commit, so give it one.
    _run_git(target, "commit", "--quiet", "--allow-empty", "-m", "init")
    new_origin = str(tmp_path / "new.git")
    subprocess.run(["git", "remote", "add", "origin", new_origin],
                   cwd=target, check=True, capture_output=True)

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("nvim;.config/nvim\n")
    store = host / "files" / "nvim"
    store.mkdir(parents=True)
    old_origin = str(tmp_path / "old.git")
    (store / ".ttgit").write_text(f"url = {old_origin}\nbranch = main\n")

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    screen = FileScreen.__new__(FileScreen)
    screen._tt_config = TTConfig(tmp_config)
    message = screen._save_repo_marker("testhost", "nvim", ".config/nvim")

    spec = read_marker(store)
    assert spec.url == new_origin
    assert spec.branch == "develop"
    assert "new.git" in message


def test_save_repo_marker_refuses_when_target_is_not_a_repo(tmp_config: Path, tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    (home / ".config" / "nvim").mkdir(parents=True)

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("nvim;.config/nvim\n")
    store = host / "files" / "nvim"
    store.mkdir(parents=True)
    old_origin = str(tmp_path / "old.git")
    (store / ".ttgit").write_text(f"url = {old_origin}\n")

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    screen = FileScreen.__new__(FileScreen)
    screen._tt_config = TTConfig(tmp_config)
    message = screen._save_repo_marker("testhost", "nvim", ".config/nvim")

    assert read_marker(store).url == old_origin
    assert "not a git repository" in message


from tui.screens.files import AddConfigPickScreen, AddFileScreen, RepoTrackChoiceScreen


def test_repo_track_choice_screen_offers_both_options(tmp_path: Path):
    screen = RepoTrackChoiceScreen(
        tmp_path / "nvim", RepoSpec(url="git@example.com:me/nvim.git", branch="main")
    )
    assert screen._source == tmp_path / "nvim"
    assert screen._spec.url == "git@example.com:me/nvim.git"


def test_add_config_pick_screen_forwards_as_repo(tmp_config: Path, tmp_path: Path, monkeypatch):
    """as_repo must reach add_path — otherwise the repo gets copied."""
    home = tmp_path / "home"
    src = home / ".config" / "nvim"
    src.mkdir(parents=True)
    (src / "init.lua").write_text("-- big\n")

    calls = {}
    cfg = TTConfig(tmp_config)
    original = cfg.add_path

    def spy(*args, **kwargs):
        calls.update(kwargs)
        return original(*args, **kwargs)

    cfg.add_path = spy
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    screen = AddConfigPickScreen.__new__(AddConfigPickScreen)
    screen._tt_config = cfg
    screen._source = src
    screen._as_repo = True
    screen._repo_spec = RepoSpec(url="git@example.com:me/nvim.git", branch="main")

    class _Sys:
        hostname = "testhost"
    screen._system = _Sys()

    screen._add_to("testhost")

    assert calls.get("as_repo") is True
    assert calls.get("repo_spec").url == "git@example.com:me/nvim.git"


def test_add_file_screen_forwards_as_repo(tmp_config: Path, tmp_path: Path, monkeypatch):
    """R5: the non-fzf ('+') add path must also forward as_repo/repo_spec —
    otherwise a repo picked via AddFileScreen always gets copied."""
    home = tmp_path / "home"
    src = home / ".config" / "nvim"
    src.mkdir(parents=True)
    (src / "init.lua").write_text("-- big\n")

    calls = {}
    cfg = TTConfig(tmp_config)
    original = cfg.add_path

    def spy(*args, **kwargs):
        calls.update(kwargs)
        return original(*args, **kwargs)

    cfg.add_path = spy
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    screen = AddFileScreen.__new__(AddFileScreen)
    screen._tt_config = cfg
    screen._selected_path = src

    class _Sys:
        hostname = "testhost"
    screen._system = _Sys()

    screen._add_selected(
        "testhost", as_repo=True,
        repo_spec=RepoSpec(url="git@example.com:me/nvim.git", branch="main"),
    )

    assert calls.get("as_repo") is True
    assert calls.get("repo_spec").url == "git@example.com:me/nvim.git"


@pytest.mark.asyncio
async def test_add_file_screen_asks_repo_question_for_a_repo_root(tmp_path: Path, monkeypatch):
    """Picking a repo root through the '+' browse flow (no fzf) must push
    RepoTrackChoiceScreen, not silently copy it."""
    home = tmp_path / "home"
    src = home / ".config" / "nvim"
    src.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", "--initial-branch=main"],
                   cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", "git@example.com:me/nvim.git"],
                   cwd=src, check=True, capture_output=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    base = tmp_path / "toolTamer"
    (base / "configs" / "testhost" / "files").mkdir(parents=True)
    (base / "configs" / "testhost" / "files.conf").write_text("")
    (base / "configs" / "testhost" / "includes.conf").write_text("")
    (base / "tt.conf").write_text("")

    system = SystemInfo()
    monkeypatch.setattr(system, "hostname", "testhost", raising=False)

    class _AddFileHarness(App):
        def on_mount(self) -> None:
            self.push_screen(AddFileScreen(TTConfig(base), system))

    app = _AddFileHarness()
    async with app.run_test() as pilot:
        add_screen = app.screen
        add_screen._set_selected(src)
        option_list = add_screen.query_one("#config-list", OptionList)
        index = next(
            i for i in range(option_list.option_count)
            if option_list.get_option_at_index(i).id == "testhost"
        )
        add_screen.on_option_list_option_selected(
            OptionList.OptionSelected(option_list, index)
        )
        await pilot.pause()
        assert isinstance(app.screen, RepoTrackChoiceScreen)
