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

from textual.widgets import DataTable, Input, RichLog

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


def test_do_apply_refuses_when_store_dir_is_unreadable(tmp_config: Path, tmp_path: Path, monkeypatch):
    """R28: an unreadable store directory must never let _do_apply's plain-
    directory branch through.

    read_marker stats a path *inside* the store dir, which needs search
    permission on the store dir itself — so on this environment (Python
    3.12.14) it raises PermissionError rather than politely reporting "no
    marker": pathlib's _ignore_error covers ENOENT/ENOTDIR/EBADF/ELOOP, not
    EACCES. Measured, not assumed. Either way the detector cannot answer the
    question, because an unreadable store dir might in fact be a repo entry
    whose .ttgit we simply cannot see — which is why the guard sits at the
    destructive step and not at the detector. sys_file, unlike the store dir, is
    perfectly readable, so shutil.rmtree(sys_file) would succeed outright —
    deleting a possibly-real repository — before shutil.copytree(repo_file,
    ...) ever got a chance to fail trying to read the source. The guard
    belongs at this destructive step, not at the (unfixable) detector."""
    import os

    home = tmp_path / "home"
    target = home / ".config" / "nvim"
    target.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", "--initial-branch=main"],
                   cwd=target, check=True, capture_output=True)
    (target / "work_in_progress.lua").write_text("-- precious\n")

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("nvim;.config/nvim\n")
    store = host / "files" / "nvim"
    store.mkdir(parents=True)
    (store / "init.lua").write_text("-- stored copy\n")
    os.chmod(store, 0o000)

    try:
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

        screen = FileScreen.__new__(FileScreen)
        screen._tt_config = TTConfig(tmp_config)
        screen._tree_cache = {}
        screen._refresh_files = lambda: None
        screen._show_diff = lambda *a, **k: None
        notifications: list[str] = []
        screen.notify = lambda msg, *a, **k: notifications.append(msg)

        screen._do_apply("testhost", "nvim", ".config/nvim")

        assert (target / "work_in_progress.lua").read_text() == "-- precious\n"
        assert (target / ".git").exists()
        assert any("unreadable" in m for m in notifications), notifications
    finally:
        os.chmod(store, 0o755)


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


def test_convertible_detects_tracked_directory_that_is_a_repo(tmp_config: Path, tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    target = home / ".config" / "nvim"
    target.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", "--initial-branch=main"],
                   cwd=target, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", "git@example.com:me/nvim.git"],
                   cwd=target, check=True, capture_output=True)

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("nvim;.config/nvim\n")
    store = host / "files" / "nvim"
    store.mkdir(parents=True)
    (store / "init.lua").write_text("-- copied\n")

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    screen = FileScreen.__new__(FileScreen)
    screen._tt_config = TTConfig(tmp_config)

    spec = screen._convertible("testhost", "nvim", ".config/nvim")
    assert spec is not None
    assert spec.url == "git@example.com:me/nvim.git"


def test_convertible_is_none_for_plain_directory(tmp_config: Path, tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    (home / ".config" / "kitty").mkdir(parents=True)

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("kitty;.config/kitty\n")
    (host / "files" / "kitty").mkdir(parents=True)

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    screen = FileScreen.__new__(FileScreen)
    screen._tt_config = TTConfig(tmp_config)

    assert screen._convertible("testhost", "kitty", ".config/kitty") is None


def test_convertible_is_none_for_an_existing_repo_entry(tmp_config: Path, tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    target = home / ".config" / "nvim"
    target.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", "--initial-branch=main"],
                   cwd=target, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", "git@example.com:me/nvim.git"],
                   cwd=target, check=True, capture_output=True)

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("nvim;.config/nvim\n")
    store = host / "files" / "nvim"
    store.mkdir(parents=True)
    (store / ".ttgit").write_text("url = git@example.com:me/nvim.git\n")

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    screen = FileScreen.__new__(FileScreen)
    screen._tt_config = TTConfig(tmp_config)

    assert screen._convertible("testhost", "nvim", ".config/nvim") is None


from tui.screens.files import ConvertToRepoScreen


def _build_convertible_dir_config(tmp_path: Path) -> tuple[Path, Path]:
    """A tmp_config with one tracked directory entry ('nvim' -> '.config/nvim')
    whose stored copy is a plain mirror while the system side is already a
    real (local, offline) git repo root — the exact situation 'g' migrates."""
    base = tmp_path / "toolTamer"
    host = base / "configs" / "testhost"
    host.mkdir(parents=True)
    (host / "files").mkdir()
    (host / "files.conf").write_text("nvim;.config/nvim\n")
    (host / "includes.conf").write_text("")
    (base / "tt.conf").write_text("")

    store = host / "files" / "nvim"
    store.mkdir(parents=True)
    (store / "init.lua").write_text("-- copied\n")

    fake_home = tmp_path / "fake_home"
    target = fake_home / ".config" / "nvim"
    target.mkdir(parents=True)
    (target / "init.lua").write_text("-- copied\n")
    _run_git(target, "init", "--quiet", "--initial-branch=main")
    _run_git(target, "config", "user.email", "t@example.com")
    _run_git(target, "config", "user.name", "Test")
    _run_git(target, "add", "init.lua")
    _run_git(target, "commit", "--quiet", "-m", "init")
    origin = str(tmp_path / "origin.git")
    _run_git(target, "remote", "add", "origin", origin)

    return base, fake_home


@pytest.mark.asyncio
async def test_show_diff_hints_at_conversion_for_a_repo_directory(tmp_path: Path):
    base, fake_home = _build_convertible_dir_config(tmp_path)
    with patch("socket.gethostname", return_value="testhost"), \
         patch.object(Path, "home", return_value=fake_home):
        app = _RepoFileScreenHarness(TTConfig(base), SystemInfo())
        async with app.run_test() as pilot:
            screen = app.screen
            worker = screen._show_diff("testhost", "nvim", ".config/nvim")
            await worker.wait()
            await pilot.pause()
            text = _extract_log_text(screen.query_one("#file-diff", RichLog))

    assert "git repository" in text
    assert "Press 'g'" in text


@pytest.mark.asyncio
async def test_convert_to_repo_does_nothing_without_confirmation(tmp_path: Path):
    """The gate is real: cancelling the dialog must leave the store untouched."""
    base, fake_home = _build_convertible_dir_config(tmp_path)
    store = base / "configs" / "testhost" / "files" / "nvim"
    with patch("socket.gethostname", return_value="testhost"), \
         patch.object(Path, "home", return_value=fake_home):
        app = _RepoFileScreenHarness(TTConfig(base), SystemInfo())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#file-table", DataTable)
            table.focus()
            table.move_cursor(row=0)
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()
            assert isinstance(app.screen, ConvertToRepoScreen)
            await pilot.press("escape")
            await pilot.pause()

    assert (store / "init.lua").exists()
    assert read_marker(store) is None


@pytest.mark.asyncio
async def test_convert_to_repo_converts_the_store_after_confirmation(tmp_path: Path):
    base, fake_home = _build_convertible_dir_config(tmp_path)
    store = base / "configs" / "testhost" / "files" / "nvim"
    target = fake_home / ".config" / "nvim"
    with patch("socket.gethostname", return_value="testhost"), \
         patch.object(Path, "home", return_value=fake_home):
        app = _RepoFileScreenHarness(TTConfig(base), SystemInfo())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#file-table", DataTable)
            table.focus()
            table.move_cursor(row=0)
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()
            assert isinstance(app.screen, ConvertToRepoScreen)
            await pilot.press("y")
            await pilot.pause()

    # Store side: mirrored file gone, replaced by a marker.
    assert not (store / "init.lua").exists()
    spec = read_marker(store)
    assert spec is not None
    assert "origin.git" in spec.url
    # System side is never touched by conversion.
    assert (target / "init.lua").read_text() == "-- copied\n"
    assert (target / ".git").exists()


# --- C1: recursive readability guard on every rmtree+copytree pair ---------

import os


class _FakeLog:
    """Stand-in for the #file-diff RichLog in non-Textual unit tests."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def clear(self) -> None:
        self.lines.clear()

    def write(self, text) -> None:
        self.lines.append(getattr(text, "plain", str(text)))


def _bare_screen(tmp_config: Path, notifications: list[str]) -> FileScreen:
    screen = FileScreen.__new__(FileScreen)
    screen._tt_config = TTConfig(tmp_config)
    screen._system = SystemInfo()
    screen._tree_cache = {}
    screen._secret_statuses = {}
    screen._secret_cache = {}
    screen._refresh_files = lambda: None
    screen._show_diff = lambda *a, **k: None
    screen.notify = lambda msg, *a, **k: notifications.append(msg)
    screen.query_one = lambda *a, **k: _FakeLog()
    return screen


def _tree_with_unreadable_subdir(root: Path) -> None:
    """top.lua readable, sub/ at mode 000 — readable at the top, not below."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "top.lua").write_text("-- top\n")
    sub = root / "sub"
    sub.mkdir()
    (sub / "deep.lua").write_text("-- deep\n")
    os.chmod(sub, 0o000)


def test_do_apply_refuses_when_a_store_subdirectory_is_unreadable(
    tmp_config: Path, tmp_path: Path, monkeypatch
):
    """C1: bin/include.sh's dirFullyReadable refuses a source that cannot be
    fully *enumerated*; Python only ever checked the top level.

    A store dir readable at the top but holding a mode-000 subdirectory
    passes os.access(R_OK|X_OK), so _do_apply fell through to
    rmtree(sys_file) + copytree(repo_file, sys_file) — and copytree raises
    shutil.Error on the unreadable subtree *after* rmtree already deleted
    the destination. Net effect: the system's sub/deep.lua is gone."""
    home = tmp_path / "home"
    target = home / ".config" / "nvim"
    _tree_with_unreadable_subdir(target)
    os.chmod(target / "sub", 0o755)

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("nvim;.config/nvim\n")
    store = host / "files" / "nvim"
    _tree_with_unreadable_subdir(store)

    try:
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        notifications: list[str] = []
        screen = _bare_screen(tmp_config, notifications)

        screen._do_apply("testhost", "nvim", ".config/nvim")

        assert (target / "sub" / "deep.lua").read_text() == "-- deep\n"
        assert sorted(p.name for p in target.iterdir()) == ["sub", "top.lua"]
        assert any("read" in m for m in notifications), notifications
    finally:
        os.chmod(store / "sub", 0o755)


def test_do_capture_refuses_when_a_system_subdirectory_is_unreadable(
    tmp_config: Path, tmp_path: Path, monkeypatch
):
    """C1, capture direction: here the *store* is the victim of the
    rmtree+copytree pair, and the unreadable subtree is on the system."""
    home = tmp_path / "home"
    sys_dir = home / ".config" / "nvim"
    _tree_with_unreadable_subdir(sys_dir)

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("nvim;.config/nvim\n")
    store = host / "files" / "nvim"
    store.mkdir(parents=True)
    (store / "top.lua").write_text("-- stored top\n")
    (store / "sub").mkdir()
    (store / "sub" / "deep.lua").write_text("-- stored deep\n")

    try:
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        notifications: list[str] = []
        screen = _bare_screen(tmp_config, notifications)

        screen._do_capture("testhost", "nvim", ".config/nvim", "parent")

        assert (store / "sub" / "deep.lua").read_text() == "-- stored deep\n"
        assert any("read" in m for m in notifications), notifications
    finally:
        os.chmod(sys_dir / "sub", 0o755)


def test_do_override_from_repo_refuses_when_source_store_is_unreadable(
    tmp_config: Path, tmp_path: Path, monkeypatch
):
    """C1, store-to-store direction: _do_override_from_repo rmtrees the host
    config's copy before copytree-ing the parent config's — same trap."""
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    common = tmp_config / "configs" / "common"
    (common / "files.conf").write_text("nvim;.config/nvim\n")
    src = common / "files" / "nvim"
    _tree_with_unreadable_subdir(src)

    host = tmp_config / "configs" / "testhost"
    dest = host / "files" / "nvim"
    dest.mkdir(parents=True)
    (dest / "keepme.lua").write_text("-- local override\n")

    try:
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        notifications: list[str] = []
        screen = _bare_screen(tmp_config, notifications)

        screen._do_override_from_repo("common", "nvim", ".config/nvim")

        assert (dest / "keepme.lua").read_text() == "-- local override\n"
        assert any("read" in m for m in notifications), notifications
    finally:
        os.chmod(src / "sub", 0o755)


# --- I1 knock-ons: messages the user can act on ---------------------------


def _repo_without_origin(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--quiet", "--initial-branch=main"],
                   cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "upstream", "git@example.com:me/nvim.git"],
                   cwd=path, check=True, capture_output=True)


def test_save_repo_marker_says_the_origin_is_missing_not_that_it_is_no_repo(
    tmp_config: Path, tmp_path: Path, monkeypatch
):
    """I1 knock-on: a repo whose remote was renamed origin -> upstream is a
    perfectly good repository. Telling the user it "is not a git repository
    root" is something they cannot act on."""
    home = tmp_path / "home"
    _repo_without_origin(home / ".config" / "nvim")

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
    assert "origin" in message
    assert "not a git repository" not in message


def test_convert_blocked_reason_names_the_missing_origin(
    tmp_config: Path, tmp_path: Path, monkeypatch
):
    """Same knock-on for `g`: _convertible returns None for a repo root
    without an origin, and the notification said "Only tracked directories
    whose system path is a git repo root can be converted" — which is false
    and unactionable for a directory that IS a git repo root."""
    home = tmp_path / "home"
    _repo_without_origin(home / ".config" / "nvim")

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("nvim;.config/nvim\n")
    (host / "files" / "nvim").mkdir(parents=True)

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    screen = FileScreen.__new__(FileScreen)
    screen._tt_config = TTConfig(tmp_config)

    assert screen._convertible("testhost", "nvim", ".config/nvim") is None
    reason = screen._convert_blocked_reason("testhost", "nvim", ".config/nvim")
    assert "origin" in reason


def test_convert_blocked_reason_for_a_plain_directory(
    tmp_config: Path, tmp_path: Path, monkeypatch
):
    home = tmp_path / "home"
    (home / ".config" / "kitty").mkdir(parents=True)

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("kitty;.config/kitty\n")
    (host / "files" / "kitty").mkdir(parents=True)

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    screen = FileScreen.__new__(FileScreen)
    screen._tt_config = TTConfig(tmp_config)

    reason = screen._convert_blocked_reason("testhost", "kitty", ".config/kitty")
    assert "git repository root" in reason


def test_convert_blocked_reason_for_an_existing_repo_entry(
    tmp_config: Path, tmp_path: Path, monkeypatch
):
    home = tmp_path / "home"
    target = home / ".config" / "nvim"
    target.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", "--initial-branch=main"],
                   cwd=target, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", "git@example.com:me/nvim.git"],
                   cwd=target, check=True, capture_output=True)

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("nvim;.config/nvim\n")
    store = host / "files" / "nvim"
    store.mkdir(parents=True)
    (store / ".ttgit").write_text("url = git@example.com:me/nvim.git\n")

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    screen = FileScreen.__new__(FileScreen)
    screen._tt_config = TTConfig(tmp_config)

    reason = screen._convert_blocked_reason("testhost", "nvim", ".config/nvim")
    assert "already" in reason.lower()


# --- I2: `a` on a healthy repo entry must not offer to delete the repo ----


@pytest.mark.asyncio
async def test_apply_on_a_repo_entry_never_shows_the_deletion_dialog(tmp_path: Path):
    """I2: action_apply_to_system computed _dir_deletions before any repo
    check. A repo entry's store holds one file (.ttgit) and the system holds
    the whole clone, so every file in the repository — all of .git included —
    was listed as "would be deleted" under a "delete and apply" caption.
    _do_apply's guard then routed to sync_to_system and deleted nothing, so
    it was harmless — and that is the problem: it trains the user to click
    through the one dialog that exists to stop them."""
    from tui.screens.files import ConfirmDeletionsScreen, _dir_deletions

    base, fake_home = _build_repo_entry_config(tmp_path)
    store = base / "configs" / "common" / "files" / "myrepo"
    # The bogus deletion list this used to raise a dialog about:
    assert len(_dir_deletions(store, fake_home / ".myrepo")) > 1

    with patch("socket.gethostname", return_value="testhost"), \
         patch.object(Path, "home", return_value=fake_home):
        app = _RepoFileScreenHarness(TTConfig(base), SystemInfo())
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            applied: list[tuple] = []
            screen._do_apply = lambda *a: applied.append(a)
            screen.action_apply_to_system()
            await pilot.pause()
            pushed = [type(s).__name__ for s in app.screen_stack]

    assert ConfirmDeletionsScreen.__name__ not in pushed, pushed
    assert applied == [("common", "myrepo", ".myrepo")]


# --- I3 (spec §5): content besides .ttgit is ignored — and now said so -----


def test_repo_detail_lines_report_content_ignored_beside_the_marker(tmp_path: Path):
    """Spec §5: "Marker-Verzeichnis enthält außer .ttgit noch Inhalt →
    .ttgit gewinnt, Rest wird ignoriert und einmalig gemeldet". The ignoring
    was implemented; the reporting was implemented nowhere, so the leftover
    files were invisible to the user."""
    store = tmp_path / "store"
    store.mkdir()
    write_marker(store, RepoSpec(url="git@example.com:me/r.git", branch="main"))
    (store / "leftover.lua").write_text("-- from before the conversion\n")
    (store / "sub").mkdir()
    (store / "sub" / "more.lua").write_text("-- also ignored\n")

    lines = FileScreen._repo_detail_lines(
        RepoSpec(url="git@example.com:me/r.git", branch="main"),
        tmp_path / "nope",
        store,
    )
    text = "\n".join(t for t, _ in lines)
    assert "ignored" in text.lower()
    assert "leftover.lua" in text
    assert "sub/more.lua" in text


def test_repo_detail_lines_say_nothing_when_only_the_marker_is_stored(tmp_path: Path):
    store = tmp_path / "store"
    store.mkdir()
    write_marker(store, RepoSpec(url="git@example.com:me/r.git", branch="main"))

    lines = FileScreen._repo_detail_lines(
        RepoSpec(url="git@example.com:me/r.git", branch="main"),
        tmp_path / "nope",
        store,
    )
    text = "\n".join(t for t, _ in lines)
    assert "ignored" not in text.lower()


def test_repo_detail_lines_name_both_branches_on_a_mismatch(tmp_path: Path, monkeypatch):
    """I4: "Diverged from the remote — sync skips this repo" described
    something that never happened. The pane must say which branch is checked
    out and which the marker names."""
    monkeypatch.setattr(repo_mod, "status", lambda *a, **k: "wrong_branch")
    monkeypatch.setattr(repo_mod, "current_branch", lambda *a, **k: "wip")

    lines = FileScreen._repo_detail_lines(
        RepoSpec(url="git@example.com:me/r.git", branch="main"), tmp_path
    )
    text = "\n".join(t for t, _ in lines)
    assert "wrong_branch" in text
    assert "wip" in text
    assert "main" in text


# --- minors ---------------------------------------------------------------


def test_repo_detail_lines_count_against_the_same_branch_status_used(tmp_path: Path):
    """The pane computed ahead/behind with `spec.branch or "HEAD"` while
    status() used _effective_branch. With no branch in the marker and no
    origin/HEAD to resolve, the pane printed "Behind the remote" over
    "0 ahead / 0 behind" — or, as here, over no counts at all."""
    origin = _make_origin_repo(tmp_path / "origin.git")
    _run_git(origin, "branch", "dev")
    clone_dir = tmp_path / "clone"
    subprocess.run(["git", "clone", "--quiet", str(origin), str(clone_dir)],
                   check=True, capture_output=True)
    _run_git(clone_dir, "config", "user.email", "t@example.com")
    _run_git(clone_dir, "config", "user.name", "Test")
    # the remote's default branch is not the one we are on
    _run_git(clone_dir, "remote", "set-head", "origin", "dev")
    # move origin/main ahead, then fetch so the local refs know about it
    (origin / "second.txt").write_text("two\n")
    _run_git(origin, "add", "second.txt")
    _run_git(origin, "commit", "--quiet", "-m", "second")
    _run_git(clone_dir, "fetch", "--quiet", "origin")

    spec = RepoSpec(url=str(origin))  # no branch in the marker
    assert repo_mod.status(clone_dir, spec) == "behind"

    lines = FileScreen._repo_detail_lines(spec, clone_dir)
    text = "\n".join(t for t, _ in lines)
    assert "Behind the remote" in text
    assert "0 ahead / 1 behind" in text, text


def test_save_repo_marker_preserves_an_existing_force_flag(
    tmp_config: Path, tmp_path: Path, monkeypatch
):
    """`force` authorises `git reset --hard`, so losing it on a marker
    refresh silently disarms the user's own opt-in. bash's
    captureRepoFromSystem has two tests for this; Python had none."""
    home = tmp_path / "home"
    target = home / ".config" / "nvim"
    target.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", "--initial-branch=main"],
                   cwd=target, check=True, capture_output=True)
    new_origin = "git@example.com:me/moved.git"
    subprocess.run(["git", "remote", "add", "origin", new_origin],
                   cwd=target, check=True, capture_output=True)

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("nvim;.config/nvim\n")
    store = host / "files" / "nvim"
    store.mkdir(parents=True)
    (store / ".ttgit").write_text(
        f"url    = {tmp_path / 'old.git'}\nbranch = main\nforce  = true\n"
    )

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    screen = FileScreen.__new__(FileScreen)
    screen._tt_config = TTConfig(tmp_config)
    message = screen._save_repo_marker("testhost", "nvim", ".config/nvim")

    updated = read_marker(store)
    assert updated.url == new_origin
    assert updated.force is True, message


@pytest.mark.asyncio
async def test_filtering_does_not_recompute_repo_status(tmp_path: Path):
    """_load_files ran repo_mod.status() synchronously on the main thread for
    every repo entry — six git subprocesses, ~38 ms each — and
    on_input_changed called _load_files again on every keystroke in the
    filter box. Filtering now re-renders the rows the last pass built.

    (The threaded detail-pane worker still recomputes the state of the one
    highlighted entry when the cursor lands on a row; that is one call
    regardless of how many entries exist, and it is off the main thread.)"""
    base, fake_home = _build_repo_entry_config(tmp_path)

    with patch("socket.gethostname", return_value="testhost"), \
         patch.object(Path, "home", return_value=fake_home):
        app = _RepoFileScreenHarness(TTConfig(base), SystemInfo())
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen

            builds: list[int] = []
            real_build = screen._build_rows
            screen._build_rows = lambda: (builds.append(1), real_build())[1]

            filter_input = screen.query_one("#file-filter", Input)
            table = screen.query_one("#file-table", DataTable)

            filter_input.value = "myrepo"
            await pilot.pause()
            assert builds == []
            assert table.row_count == 1

            filter_input.value = "nothing-matches-this"
            await pilot.pause()
            assert builds == []
            assert table.row_count == 0

            filter_input.value = ""
            await pilot.pause()
            assert builds == []
            assert table.row_count == 1

            # an explicit refresh still rebuilds
            screen._refresh_files()
            await pilot.pause()
            assert builds == [1]


def test_save_change_reports_an_unreadable_store_instead_of_raising(
    tmp_config: Path, tmp_path: Path, monkeypatch
):
    """action_save_change called read_marker with no access guard, so an
    unreadable store directory raised PermissionError straight out of the `u`
    key handler. _do_apply has carried this guard since C1; `u` did not."""
    import os

    home = tmp_path / "home"
    (home / ".config" / "nvim").mkdir(parents=True)

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("nvim;.config/nvim\n")
    store = host / "files" / "nvim"
    store.mkdir(parents=True)
    (store / "init.lua").write_text("-- stored\n")
    os.chmod(store, 0o000)

    try:
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        screen = _bare_screen(tmp_config, [])
        log = _FakeLog()
        screen.query_one = lambda *a, **k: log
        screen._get_selected = lambda: ("testhost", "nvim", ".config/nvim")

        screen.action_save_change()

        assert any("unreadable" in line for line in log.lines), log.lines
    finally:
        os.chmod(store, 0o755)


# --- Directory copies must keep symlinks as symlinks ----------------------


from tui.core.config import dir_diff, tree_hash
from tui.core.system import SystemInfo as _SystemInfo


def _tree_with_symlinks(root: Path) -> None:
    """A package-manager-style tree: real files plus a relative symlink and a
    dangling one, which is what node_modules/.bin actually looks like."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "bin").mkdir()
    (root / "lib").mkdir()
    (root / "lib" / "cli.js").write_text("#!/usr/bin/env node\n")
    (root / "bin" / "cli").symlink_to("../lib/cli.js")
    (root / "bin" / "dangling").symlink_to("../lib/gone.js")


def test_do_capture_keeps_symlinks_as_symlinks(tmp_config: Path, tmp_path: Path, monkeypatch):
    """Regression: _do_capture's copytree had no symlinks=True, so copytree's
    default (symlinks=False) dereferenced every symlink on the way into the
    store — node_modules/.bin/* arrived as regular files.

    iter_tree_files/_entry_fingerprint identify a symlink by its target
    ("link:../lib/cli.js") and a regular file by its content, so the two trees
    can never compare equal again: _file_status reports "modified" forever and
    pressing u just re-dereferences the copy. That is the reported symptom —
    the stored copy of ~/.config/opencode could not be updated.

    Delete-and-recreate also means a vanished regular file (like a .bin entry
    that was never a symlink) must not survive the capture."""
    import os

    home = tmp_path / "home"
    sys_dir = home / ".config" / "opencode"
    _tree_with_symlinks(sys_dir)

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text(".config/opencode;.config/opencode\n")
    store = host / "files" / ".config" / "opencode"
    store.mkdir(parents=True)
    (store / "stale.txt").write_text("old\n")

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    screen = _bare_screen(tmp_config, [])

    screen._do_capture("testhost", ".config/opencode", ".config/opencode", "parent")

    assert (store / "bin" / "cli").is_symlink()
    assert os.readlink(store / "bin" / "cli") == "../lib/cli.js"
    assert (store / "bin" / "dangling").is_symlink()
    assert not (store / "stale.txt").exists()
    assert tree_hash(store) == tree_hash(sys_dir)
    assert dir_diff(store, sys_dir) == ([], [], [])
    assert screen._file_status(store, sys_dir) == "ok"


def test_do_apply_keeps_symlinks_as_symlinks(tmp_config: Path, tmp_path: Path, monkeypatch):
    """The apply direction had the same gap: a store→system copy materialised
    regular files where the tracked tree has symlinks, breaking the package
    manager's bins on the target machine (and bash's mirrorDir — rsync -a —
    keeps them, so the two implementations disagreed)."""
    import os

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    target = home / ".config" / "opencode"

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text(".config/opencode;.config/opencode\n")
    store = host / "files" / ".config" / "opencode"
    _tree_with_symlinks(store)

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    screen = _bare_screen(tmp_config, [])

    screen._do_apply("testhost", ".config/opencode", ".config/opencode")

    assert (target / "bin" / "cli").is_symlink()
    assert os.readlink(target / "bin" / "cli") == "../lib/cli.js"
    assert (target / "bin" / "dangling").is_symlink()
    assert tree_hash(target) == tree_hash(store)
    assert dir_diff(target, store) == ([], [], [])


def test_do_override_from_repo_keeps_symlinks_as_symlinks(
    tmp_config: Path, tmp_path: Path, monkeypatch
):
    """Store-to-store, third site: the host's local copy is the one the user
    then edits and captures back, so a dereferenced override would keep the
    entry "modified" even after that capture."""
    import os

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    common = tmp_config / "configs" / "common"
    (common / "files.conf").write_text(".config/opencode;.config/opencode\n")
    src = common / "files" / ".config" / "opencode"
    _tree_with_symlinks(src)

    host_name = _SystemInfo().hostname
    dest = tmp_config / "configs" / host_name / "files" / ".config" / "opencode"

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    screen = _bare_screen(tmp_config, [])

    screen._do_override_from_repo("common", ".config/opencode", ".config/opencode")

    assert (dest / "bin" / "cli").is_symlink()
    assert os.readlink(dest / "bin" / "cli") == "../lib/cli.js"
    assert (dest / "bin" / "dangling").is_symlink()
    assert tree_hash(dest) == tree_hash(src)


# --- ignore rules in the file manager ------------------------------------


from tui.core.ignore import load as _load  # noqa: E402
from tui.screens.files import ReviewNewFilesScreen, _new_system_files  # noqa: E402


class _ReviewApp(App):
    """Host app that pushes a ReviewNewFilesScreen and records its result."""

    def __init__(self, screen):
        super().__init__()
        self._screen = screen
        self.result = "unset"

    def on_mount(self) -> None:
        self.push_screen(self._screen, callback=self._on_result)

    def _on_result(self, result) -> None:
        self.result = result


@pytest.mark.asyncio
async def test_review_new_files_defaults_to_adopt():
    from textual.widgets import SelectionList

    screen = ReviewNewFilesScreen("Apply TT → ~/.config/app", ["a.txt", "b.txt"])
    app = _ReviewApp(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        sl = screen.query_one(SelectionList)
        assert sorted(sl.selected) == ["a.txt", "b.txt"]
        await pilot.press("enter")
        await pilot.pause()
    assert app.result == {"a.txt": True, "b.txt": True}


@pytest.mark.asyncio
async def test_review_new_files_toggle_one_row_to_ignore():
    from textual.widgets import SelectionList

    screen = ReviewNewFilesScreen("Capture ~/.config/app", ["a.txt", "b.txt"])
    app = _ReviewApp(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen.query_one(SelectionList).toggle("a.txt")
        await pilot.press("enter")
        await pilot.pause()
    assert app.result == {"a.txt": False, "b.txt": True}


@pytest.mark.asyncio
async def test_review_new_files_ignore_all():
    screen = ReviewNewFilesScreen("Capture ~/.config/app", ["a.txt", "b.txt"])
    app = _ReviewApp(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.press("enter")
        await pilot.pause()
    assert app.result == {"a.txt": False, "b.txt": False}


@pytest.mark.asyncio
async def test_review_new_files_escape_aborts():
    screen = ReviewNewFilesScreen("Capture ~/.config/app", ["a.txt"])
    app = _ReviewApp(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None


def test_new_system_files_excludes_store_and_ignored(tmp_path: Path):
    store = tmp_path / "store"
    system = tmp_path / "system"
    for d in (store, system):
        d.mkdir()
        (d / ".gitignore").write_text("local.txt\n")
    (store / "keep.txt").write_text("k\n")
    (system / "keep.txt").write_text("k\n")
    (system / "fresh.txt").write_text("f\n")
    (system / "local.txt").write_text("l\n")

    assert _new_system_files(store, system, _load(system)) == ["fresh.txt"]


def test_do_apply_keeps_an_ignored_system_file(tmp_config: Path, tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    sys_dir = home / ".config" / "app"
    sys_dir.mkdir(parents=True)
    (sys_dir / ".gitignore").write_text("local.txt\ncache/\n")
    (sys_dir / "keep.txt").write_text("keep\n")
    (sys_dir / "local.txt").write_text("mine\n")

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("app;.config/app\n")
    store = host / "files" / "app"
    store.mkdir(parents=True)
    (store / ".gitignore").write_text("local.txt\ncache/\n")
    (store / "keep.txt").write_text("keep\n")
    (store / "new.txt").write_text("new\n")
    (store / "cache").mkdir()
    (store / "cache" / "secret").write_text("s\n")

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    screen = _bare_screen(tmp_config, [])

    screen._do_apply("testhost", "app", ".config/app")

    # Ignored system file survives, the ignored store cache is not delivered.
    assert (sys_dir / "local.txt").read_text() == "mine\n"
    assert not (sys_dir / "cache").exists()
    assert (sys_dir / "new.txt").read_text() == "new\n"


def test_do_capture_does_not_capture_an_ignored_file(tmp_config: Path, tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    sys_dir = home / ".config" / "app"
    sys_dir.mkdir(parents=True)
    (sys_dir / ".gitignore").write_text("local.txt\n")
    (sys_dir / "keep.txt").write_text("keep\n")
    (sys_dir / "local.txt").write_text("mine\n")

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("app;.config/app\n")
    store = host / "files" / "app"
    store.mkdir(parents=True)
    (store / "stale.txt").write_text("stale\n")

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    screen = _bare_screen(tmp_config, [])

    screen._do_capture("testhost", "app", ".config/app", "parent")

    assert (store / "keep.txt").read_text() == "keep\n"
    assert (store / ".gitignore").is_file()
    assert not (store / "local.txt").exists()
    assert not (store / "stale.txt").exists()


def test_process_review_ignore_writes_ttignore_on_both_sides(
    tmp_config: Path, tmp_path: Path, monkeypatch
):
    home = tmp_path / "home"
    sys_dir = home / ".config" / "app"
    sys_dir.mkdir(parents=True)
    (sys_dir / "token.json").write_text("{}\n")

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("app;.config/app\n")
    store = host / "files" / "app"
    store.mkdir(parents=True)

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    screen = _bare_screen(tmp_config, [])

    screen._process_review(store, sys_dir, {"token.json": False})

    assert "/token.json" in (sys_dir / ".ttignore").read_text()
    assert "/token.json" in (store / ".ttignore").read_text()
    assert _load(sys_dir).is_ignored("token.json")


def test_process_review_adopt_copies_into_the_store(
    tmp_config: Path, tmp_path: Path, monkeypatch
):
    home = tmp_path / "home"
    sys_dir = home / ".config" / "app"
    sys_dir.mkdir(parents=True)
    (sys_dir / "new.txt").write_text("new\n")

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("app;.config/app\n")
    store = host / "files" / "app"
    store.mkdir(parents=True)

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    screen = _bare_screen(tmp_config, [])

    screen._process_review(store, sys_dir, {"new.txt": True})

    assert (store / "new.txt").read_text() == "new\n"
    assert not (sys_dir / ".ttignore").exists()


def _review_setup(tmp_config: Path, tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    sys_dir = home / ".config" / "app"
    sys_dir.mkdir(parents=True)
    (sys_dir / "keep.txt").write_text("keep\n")
    (sys_dir / "fresh.txt").write_text("fresh\n")

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("app;.config/app\n")
    store = host / "files" / "app"
    store.mkdir(parents=True)
    (store / "keep.txt").write_text("keep\n")

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return store, sys_dir, _bare_screen(tmp_config, [])


def test_after_apply_review_escape_aborts_the_sync(tmp_config: Path, tmp_path: Path, monkeypatch):
    store, sys_dir, screen = _review_setup(tmp_config, tmp_path, monkeypatch)

    screen._after_apply_review("testhost", "app", ".config/app", None)

    # Nothing was mirrored and nothing was ignored.
    assert (sys_dir / "fresh.txt").is_file()
    assert not (store / "fresh.txt").exists()
    assert not (sys_dir / ".ttignore").exists()


def test_after_apply_review_adopt_keeps_and_stores_the_file(
    tmp_config: Path, tmp_path: Path, monkeypatch
):
    store, sys_dir, screen = _review_setup(tmp_config, tmp_path, monkeypatch)

    screen._after_apply_review("testhost", "app", ".config/app", {"fresh.txt": True})

    assert (sys_dir / "fresh.txt").is_file()
    assert (store / "fresh.txt").read_text() == "fresh\n"


def test_after_apply_review_ignore_writes_rules_on_both_sides(
    tmp_config: Path, tmp_path: Path, monkeypatch
):
    store, sys_dir, screen = _review_setup(tmp_config, tmp_path, monkeypatch)

    screen._after_apply_review("testhost", "app", ".config/app", {"fresh.txt": False})

    assert (sys_dir / "fresh.txt").is_file()
    assert "/fresh.txt" in (sys_dir / ".ttignore").read_text()
    assert "/fresh.txt" in (store / ".ttignore").read_text()


def test_after_capture_review_override_writes_rules_to_the_host_store(
    tmp_config: Path, tmp_path: Path, monkeypatch
):
    home = tmp_path / "home"
    sys_dir = home / ".config" / "app"
    sys_dir.mkdir(parents=True)
    (sys_dir / "fresh.txt").write_text("fresh\n")

    parent = tmp_config / "configs" / "common"
    (parent / "files.conf").write_text("app;.config/app\n")
    parent_store = parent / "files" / "app"
    parent_store.mkdir(parents=True)
    host_store = tmp_config / "configs" / _SystemInfo().hostname / "files" / "app"
    host_store.mkdir(parents=True)

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    screen = _bare_screen(tmp_config, [])

    screen._after_capture_review(
        "common", "app", ".config/app", "override", {"fresh.txt": False}
    )

    assert "/fresh.txt" in (sys_dir / ".ttignore").read_text()
    assert "/fresh.txt" in (host_store / ".ttignore").read_text()
    assert not (parent_store / ".ttignore").exists()


def test_secret_entry_appears_as_a_locked_row(tmp_config: Path, tmp_path: Path, monkeypatch):
    """A secrets.conf entry must show up in the file list (with a lock
    token and a 'secret' filter keyword) instead of being invisible."""
    host = "testhost"
    (tmp_config / "configs" / host / "secrets.conf").write_text("tok;.config/tok\n")
    (tmp_config / "configs" / host / "files" / "tok").write_bytes(
        b"age-encryption.org/v1\n"
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    system = SystemInfo()
    monkeypatch.setattr(system, "hostname", host, raising=False)
    screen = FileScreen(TTConfig(tmp_config), system)
    rows = screen._build_rows()

    secret_rows = [r for r in rows if r[0].startswith("secret ")]
    assert len(secret_rows) == 1
    assert secret_rows[0][1].plain == "S"
    assert "~/.config/tok" in secret_rows[0][2].plain


def test_secret_row_build_does_not_decrypt(tmp_config: Path, tmp_path: Path, monkeypatch):
    """Building the row list must not shell out to age: one subprocess per
    secret on the UI thread froze the file manager on open. Rows start with
    the neutral 'S' token and the real status comes from a background worker."""
    host = "testhost"
    (tmp_config / "configs" / host / "secrets.conf").write_text("tok;.config/tok\n")
    (tmp_config / "configs" / host / "files" / "tok").write_bytes(
        b"age-encryption.org/v1\n"
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    system = SystemInfo()
    monkeypatch.setattr(system, "hostname", host, raising=False)
    screen = FileScreen(TTConfig(tmp_config), system)

    def boom(*_a, **_k):
        raise AssertionError("_secret_status must not run during _build_rows")

    monkeypatch.setattr(screen, "_secret_status", boom)
    rows = screen._build_rows()
    secret_rows = [r for r in rows if r[0].startswith("secret ")]
    assert secret_rows
    assert secret_rows[0][1].plain == "S"


@pytest.mark.asyncio
async def test_select_secret_files_screen_lists_candidates():
    """The directory picker shows every candidate and starts all-unselected
    (opt-in: selecting encrypts, leaving unselected keeps it plaintext)."""
    from textual.widgets import SelectionList
    from tui.screens.files import SelectSecretFilesScreen

    screen = SelectSecretFilesScreen("Encrypt files", ["a.json", "b.json"])
    app = _DialogApp(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        sl = screen.query_one("#select-secret-list", SelectionList)
        assert sl.option_count == 2
        assert list(sl.selected) == []


def test_apply_ignore_files_writes_rules_on_both_sides(
    tmp_config: Path, tmp_path: Path, monkeypatch
):
    """`i` on a directory: ignored inner files get an anchored .ttignore rule
    in the store *and* the system dir, so the mirror skips them."""
    store = tmp_config / "configs" / "common" / "files" / "app"
    store.mkdir(parents=True)
    (tmp_config / "configs" / "common" / "files.conf").write_text("app;.config/app\n")
    home = tmp_path / "home"
    sys_dir = home / ".config" / "app"
    sys_dir.mkdir(parents=True)

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    notes: list[str] = []
    screen = _bare_screen(tmp_config, notes)
    screen._apply_ignore_files("common", "app", ".config/app", ["cache.db"])

    assert (store / ".ttignore").read_text().strip() == "/cache.db"
    assert (sys_dir / ".ttignore").read_text().strip() == "/cache.db"
