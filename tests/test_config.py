from pathlib import Path

import pytest

from tui.core.config import TTConfig
from tui.core.repo import RepoSpec


def test_list_configs(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    names = cfg.list_configs()
    assert "common" in names
    assert "macosx" in names
    assert "testhost" in names


def test_get_includes(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    includes = cfg.get_includes("testhost")
    assert includes == ["macosx"]


def test_get_includes_common_has_none(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    includes = cfg.get_includes("common")
    assert includes == []


def test_get_parents(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    parents = cfg.get_parents("testhost")
    assert "common" in parents
    assert "macosx" in parents


def test_get_packages(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    pkgs = cfg.get_packages("testhost", "brew")
    assert "ollama" in pkgs
    assert "postgresql" in pkgs


def test_get_effective_packages(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    effective = cfg.get_effective_packages("testhost", "brew")
    assert "git" in effective
    assert "aerospace" in effective
    assert "ollama" in effective


def test_get_files_conf(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    files = cfg.get_file_mappings("testhost")
    assert ("kitty.conf", ".config/kitty/kitty.conf") in files


def test_get_effective_file_mappings(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    mappings = cfg.get_effective_file_mappings("testhost")
    targets = [m.target for m in mappings]
    assert ".config/kitty/kitty.conf" in targets
    assert ".aerospace.toml" in targets
    assert ".zshrc" in targets


def test_effective_target_resolves_directory_targets(tmp_config: Path):
    """When target ends with '/', the file lands at target+basename(stored),
    matching include.sh's createEffectiveFilesList behavior."""
    common = tmp_config / "configs" / "common"
    (common / "files.conf").write_text(
        "ssh/id_rsa;.ssh/\nssh/id_rsa.pub;.ssh/\nstarship.toml;.config/starship.toml\n"
    )
    cfg = TTConfig(tmp_config)
    mappings = {m.stored: m.effective_target for m in cfg.get_effective_file_mappings("testhost")}
    assert mappings["ssh/id_rsa"] == ".ssh/id_rsa"
    assert mappings["ssh/id_rsa.pub"] == ".ssh/id_rsa.pub"
    # Non-directory target stays unchanged
    assert mappings["starship.toml"] == ".config/starship.toml"


def test_within_config_duplicates_are_marked_shadowed(tmp_config: Path):
    """Two lines in the same files.conf that resolve to the same effective
    target (e.g. `wezterm/x.lua;.config/wezterm/` and `.config/wezterm/x.lua;
    .config/wezterm/x.lua`) — last-write-wins, the other is shadowed."""
    macosx = tmp_config / "configs" / "macosx"
    (macosx / "files.conf").write_text(
        "wezterm/x.lua;.config/wezterm/\n"
        ".config/wezterm/x.lua;.config/wezterm/x.lua\n"
    )
    cfg = TTConfig(tmp_config)
    rows = [
        m for m in cfg.get_effective_file_mappings("testhost")
        if m.effective_target == ".config/wezterm/x.lua"
    ]
    effective = [m for m in rows if m.is_effective]
    assert len(rows) == 2
    assert len(effective) == 1
    assert effective[0].stored == ".config/wezterm/x.lua"


def test_get_effective_file_mappings_exposes_shadowed_duplicates(tmp_config: Path):
    """When the same target is mapped from multiple configs in the chain,
    all entries are returned and the deepest one wins (is_effective=True)."""
    # Add a duplicate .zshrc mapping to testhost (already mapped in common)
    host_conf = tmp_config / "configs" / "testhost" / "files.conf"
    host_conf.write_text(host_conf.read_text() + "host_zshrc;.zshrc\n")

    cfg = TTConfig(tmp_config)
    zshrc = [m for m in cfg.get_effective_file_mappings("testhost") if m.target == ".zshrc"]

    # Both mappings (from common and testhost) must be present
    configs = sorted(m.config for m in zshrc)
    assert configs == ["common", "testhost"]

    # Deepest in chain wins; the other is shadowed
    winner = next(m for m in zshrc if m.is_effective)
    shadowed = next(m for m in zshrc if not m.is_effective)
    assert winner.config == "testhost"
    assert shadowed.config == "common"
    assert shadowed.shadowed_by == "testhost"


def test_remove_file_deletes_orphaned_stored_copy(sample_files: Path):
    """Removing a file mapping must also delete its stored copy, otherwise it
    becomes an orphan in configs/<config>/files/ that is no longer referenced
    by files.conf."""
    cfg = TTConfig(sample_files)
    stored_copy = sample_files / "configs" / "testhost" / "files" / "kitty.conf"
    assert stored_copy.exists()

    deleted = cfg.remove_file("testhost", "kitty.conf", ".config/kitty/kitty.conf")

    assert deleted is True
    assert not stored_copy.exists()
    assert ("kitty.conf", ".config/kitty/kitty.conf") not in cfg.get_file_mappings("testhost")


def test_remove_file_keeps_stored_copy_still_referenced(sample_files: Path):
    """When two mappings share the same stored file, removing one must NOT
    delete the stored copy the other still points at."""
    host_conf = sample_files / "configs" / "testhost" / "files.conf"
    host_conf.write_text(host_conf.read_text() + "kitty.conf;.config/kitty/other.conf\n")
    cfg = TTConfig(sample_files)
    stored_copy = sample_files / "configs" / "testhost" / "files" / "kitty.conf"

    deleted = cfg.remove_file("testhost", "kitty.conf", ".config/kitty/kitty.conf")

    assert deleted is False
    assert stored_copy.exists()
    assert ("kitty.conf", ".config/kitty/other.conf") in cfg.get_file_mappings("testhost")


def test_resolve_chain(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    chain = cfg.resolve_chain("testhost")
    assert chain == ["common", "macosx", "testhost"]


def test_move_package(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    cfg.move_package("testhost", "common", "ollama", "brew")
    assert "ollama" not in cfg.get_packages("testhost", "brew")
    assert "ollama" in cfg.get_packages("common", "brew")


def test_copy_package(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    cfg.copy_package("testhost", "common", "ollama", "brew")
    assert "ollama" in cfg.get_packages("testhost", "brew")
    assert "ollama" in cfg.get_packages("common", "brew")


def test_get_taps(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    taps = cfg.get_taps("testhost")
    assert "nikitabobko/tap" in taps


def test_get_children(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    children = cfg.get_children("macosx")
    assert "testhost" in children


def test_file_mapping_without_marker_is_not_a_repo(tmp_config: Path):
    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("kitty.conf;.config/kitty/kitty.conf\n")
    cfg = TTConfig(tmp_config)
    m = next(m for m in cfg.get_effective_file_mappings("testhost")
             if m.stored == "kitty.conf")
    assert m.is_repo is False
    assert m.repo is None


def test_file_mapping_with_marker_is_a_repo(tmp_config: Path):
    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("nvim;.config/nvim\n")
    store = host / "files" / "nvim"
    store.mkdir(parents=True)
    (store / ".ttgit").write_text("url = git@example.com:me/nvim.git\nbranch = main\n")
    cfg = TTConfig(tmp_config)
    m = next(m for m in cfg.get_effective_file_mappings("testhost")
             if m.stored == "nvim")
    assert m.is_repo is True
    assert m.repo is not None
    assert m.repo.url == "git@example.com:me/nvim.git"
    assert m.repo.branch == "main"


def test_add_path_as_repo_writes_only_the_marker(tmp_config: Path, tmp_path: Path):
    home = tmp_path / "home"
    src = home / ".config" / "nvim"
    src.mkdir(parents=True)
    (src / "init.lua").write_text("-- big file\n")

    cfg = TTConfig(tmp_config)
    cfg.add_path(
        "testhost", src, home=home, as_repo=True,
        repo_spec=RepoSpec(url="git@example.com:me/nvim.git", branch="main"),
    )

    store = tmp_config / "configs" / "testhost" / "files" / ".config" / "nvim"
    assert (store / ".ttgit").is_file()
    assert not (store / "init.lua").exists()
    assert ".config/nvim;.config/nvim" in (
        tmp_config / "configs" / "testhost" / "files.conf"
    ).read_text()


def test_add_path_as_repo_reports_error_when_source_is_not_a_git_repo(
    tmp_config: Path, tmp_path: Path
):
    home = tmp_path / "home"
    src = home / ".config" / "nvim"
    src.mkdir(parents=True)
    (src / "init.lua").write_text("-- not a repo\n")

    cfg = TTConfig(tmp_config)
    report = cfg.add_path("testhost", src, home=home, as_repo=True)

    assert any("not a git repository root" in line for line in report)
    store = tmp_config / "configs" / "testhost" / "files" / ".config" / "nvim"
    assert not store.exists()
    assert ".config/nvim" not in (
        tmp_config / "configs" / "testhost" / "files.conf"
    ).read_text()


def test_add_path_as_repo_warns_about_overlapping_mappings_in_other_configs(
    tmp_config: Path, tmp_path: Path
):
    # macosx is testhost's parent in the chain (common -> macosx -> testhost);
    # give it a mapping whose effective target lies inside the directory
    # about to be added as a repo entry to testhost.
    macosx = tmp_config / "configs" / "macosx"
    (macosx / "files.conf").write_text(
        "aerospace.toml;.aerospace.toml\ninit.lua;.config/nvim/init.lua\n"
    )

    home = tmp_path / "home"
    src = home / ".config" / "nvim"
    src.mkdir(parents=True)
    (src / "init.lua").write_text("-- big file\n")

    cfg = TTConfig(tmp_config)
    report = cfg.add_path(
        "testhost", src, home=home, as_repo=True,
        repo_spec=RepoSpec(url="git@example.com:me/nvim.git", branch="main"),
    )

    assert any(
        "WARNING" in line and ".config/nvim/init.lua" in line and "macosx" in line
        for line in report
    )


def test_convert_to_repo_removes_stored_content(tmp_config: Path):
    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("nvim;.config/nvim\n")
    store = host / "files" / "nvim"
    (store / "lua").mkdir(parents=True)
    (store / "init.lua").write_text("-- copied\n")
    (store / "lua" / "opts.lua").write_text("-- copied\n")

    cfg = TTConfig(tmp_config)
    report = cfg.convert_to_repo(
        "testhost", "nvim", RepoSpec(url="git@example.com:me/nvim.git", branch="main")
    )

    assert (store / ".ttgit").is_file()
    assert not (store / "init.lua").exists()
    assert not (store / "lua").exists()
    assert any("nvim" in line for line in report)


def test_convert_to_repo_keeps_the_files_conf_entry(tmp_config: Path):
    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("nvim;.config/nvim\n")
    (host / "files" / "nvim").mkdir(parents=True)
    (host / "files" / "nvim" / "init.lua").write_text("x\n")

    cfg = TTConfig(tmp_config)
    cfg.convert_to_repo("testhost", "nvim", RepoSpec(url="u", branch="main"))

    assert cfg.get_file_mappings("testhost") == [("nvim", ".config/nvim")]


# --- C1: recursive readability check --------------------------------------

def test_dir_fully_readable_accepts_a_readable_tree(tmp_path: Path):
    from tui.core.config import dir_fully_readable

    root = tmp_path / "tree"
    (root / "sub").mkdir(parents=True)
    (root / "top.txt").write_text("t\n")
    (root / "sub" / "deep.txt").write_text("d\n")
    assert dir_fully_readable(root) is True


def test_dir_fully_readable_rejects_an_unreadable_top_level(tmp_path: Path):
    import os
    from tui.core.config import dir_fully_readable

    root = tmp_path / "tree"
    root.mkdir()
    (root / "top.txt").write_text("t\n")
    os.chmod(root, 0o000)
    try:
        assert dir_fully_readable(root) is False
    finally:
        os.chmod(root, 0o755)


def test_dir_fully_readable_rejects_an_unreadable_subdirectory(tmp_path: Path):
    """The half iter_tree_files cannot see: os.walk swallows the scandir
    failure and reports the subtree as empty, so every check built on it
    (tree_hash, dir_diff, _dir_deletions) silently under-reports. This is
    the parity check against bin/include.sh's dirFullyReadable, which
    refuses on any `find` stderr."""
    import os
    from tui.core.config import dir_fully_readable, iter_tree_files

    root = tmp_path / "tree"
    (root / "sub").mkdir(parents=True)
    (root / "top.txt").write_text("t\n")
    (root / "sub" / "deep.txt").write_text("d\n")
    os.chmod(root / "sub", 0o000)
    try:
        # iter_tree_files sees only top.txt and reports no problem at all
        assert sorted(rel for rel, _ in iter_tree_files(root)) == ["top.txt"]
        assert dir_fully_readable(root) is False
    finally:
        os.chmod(root / "sub", 0o755)


def test_dir_fully_readable_rejects_a_missing_or_non_directory_path(tmp_path: Path):
    from tui.core.config import dir_fully_readable

    assert dir_fully_readable(tmp_path / "nope") is False
    f = tmp_path / "file.txt"
    f.write_text("x\n")
    assert dir_fully_readable(f) is False


# --- I3: a repo entry is not a directory snapshot -------------------------

def _repo_entry_config(tmp_config: Path) -> Path:
    """'.config/nvim' tracked as a repo entry in the host config."""
    from tui.core.repo import write_marker

    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("nvim;.config/nvim\n")
    store = host / "files" / "nvim"
    write_marker(store, RepoSpec(url="git@example.com:me/nvim.git", branch="main"))
    return store


def test_find_covering_dir_skips_repo_entries(tmp_config: Path):
    """I3: find_covering_dir accepted any store path that is_dir(), and a
    marker directory is one — so a repo entry looked like a directory
    snapshot covering everything under it."""
    cfg = TTConfig(tmp_config)
    _repo_entry_config(tmp_config)

    assert cfg.find_covering_dir(".config/nvim/init.lua", ["testhost"]) is None


def test_find_covering_repo_finds_the_repo_entry(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    _repo_entry_config(tmp_config)

    covering = cfg.find_covering_repo(".config/nvim/init.lua", ["testhost"])
    assert covering is not None
    assert covering.effective_target == ".config/nvim"
    assert covering.config == "testhost"


def test_adding_a_file_inside_a_repo_entry_is_refused_and_says_why(
    tmp_config: Path, tmp_path: Path
):
    """I3: add_path's regular-file branch wrote the file into the marker
    directory and reported "updated the directory snapshot, no new entry".
    Neither engine will ever sync that file — the store side of a repo entry
    holds only .ttgit — so the user was told something untrue."""
    cfg = TTConfig(tmp_config)
    store = _repo_entry_config(tmp_config)

    home = tmp_path / "home"
    src = home / ".config" / "nvim" / "init.lua"
    src.parent.mkdir(parents=True)
    src.write_text("-- init\n")

    report = cfg.add_path("testhost", src, home=home)

    assert sorted(p.name for p in store.iterdir()) == [".ttgit"]
    assert cfg.get_file_mappings("testhost") == [("nvim", ".config/nvim")]
    text = " ".join(report)
    assert "repo entry" in text
    assert "snapshot" not in text


def test_adding_a_file_is_unaffected_by_an_unrelated_unreadable_store_dir(
    tmp_config: Path, tmp_path: Path
):
    """Regression from the I3 fix: _find_covering consulted read_marker for
    every candidate store dir before checking whether it covers the path at
    all. read_marker stats <store>/.ttgit, which needs search permission on
    the store dir and raises on this environment — so one unreadable tracked
    directory anywhere in scope broke `n` for every regular file, as an
    unhandled exception in a Textual key handler."""
    import os

    cfg = TTConfig(tmp_config)
    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("secretdir;.config/secretdir\n")
    secret = host / "files" / "secretdir"
    secret.mkdir(parents=True)
    (secret / "inner.txt").write_text("x\n")
    os.chmod(secret, 0o000)

    home = tmp_path / "home"
    home.mkdir()
    src = home / "newfile.txt"
    src.write_text("hello\n")

    try:
        assert cfg.find_covering_dir("newfile.txt", ["testhost"]) is None
        report = cfg.add_path("testhost", src, home=home)
        assert report == ["Added ~/newfile.txt in 'testhost'"]
        assert (host / "files" / "newfile.txt").read_text() == "hello\n"
    finally:
        os.chmod(secret, 0o755)


def test_adding_a_file_inside_an_unreadable_tracked_directory_refuses(
    tmp_config: Path, tmp_path: Path
):
    """The other half: a store dir that DOES cover the path and cannot be
    read must not be guessed at. Treating it as a plain directory snapshot
    would write into a possible repo entry — the I3 bug again — so it is
    refused with an honest message instead."""
    import os

    cfg = TTConfig(tmp_config)
    host = tmp_config / "configs" / "testhost"
    (host / "files.conf").write_text("secretdir;.config/secretdir\n")
    secret = host / "files" / "secretdir"
    secret.mkdir(parents=True)
    (secret / "inner.txt").write_text("x\n")
    os.chmod(secret, 0o000)

    home = tmp_path / "home"
    src = home / ".config" / "secretdir" / "newfile.txt"
    src.parent.mkdir(parents=True)
    src.write_text("hello\n")

    try:
        assert cfg.find_covering_dir(".config/secretdir/newfile.txt", ["testhost"]) is None
        assert cfg.find_covering_repo(".config/secretdir/newfile.txt", ["testhost"]) is None
        covering = cfg.find_covering_unreadable(".config/secretdir/newfile.txt", ["testhost"])
        assert covering is not None and covering.effective_target == ".config/secretdir"

        report = cfg.add_path("testhost", src, home=home)
        text = " ".join(report)
        assert "cannot be read" in text
        assert "nothing added" in text
        assert cfg.get_file_mappings("testhost") == [("secretdir", ".config/secretdir")]
    finally:
        os.chmod(secret, 0o755)


# --- rename_config -------------------------------------------------------


def test_rename_config_moves_the_directory(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    cfg.rename_config("testhost", "gandalf")
    assert not (tmp_config / "configs" / "testhost").exists()
    assert (tmp_config / "configs" / "gandalf" / "to_install.brew").read_text() == "ollama\npostgresql\n"
    assert "gandalf" in cfg.list_configs()


def test_rename_config_refuses_to_clobber_existing(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    with pytest.raises(FileExistsError):
        cfg.rename_config("testhost", "macosx")
    assert (tmp_config / "configs" / "testhost").is_dir()


def test_rename_config_refuses_missing_source(tmp_config: Path):
    cfg = TTConfig(tmp_config)
    with pytest.raises(FileNotFoundError):
        cfg.rename_config("nope", "gandalf")
