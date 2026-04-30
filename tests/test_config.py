from pathlib import Path
from tui.core.config import TTConfig


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
