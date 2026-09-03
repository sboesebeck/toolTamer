from pathlib import Path
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
