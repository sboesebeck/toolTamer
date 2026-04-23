"""Config hierarchy tree widget."""

from textual.widgets import Tree

from tui.core.config import TTConfig


class ConfigTree(Tree):
    """Displays the config include hierarchy."""

    def __init__(self, tt_config: TTConfig, host: str, **kwargs):
        super().__init__("configs", **kwargs)
        self._tt_config = tt_config
        self._host = host

    def on_mount(self) -> None:
        self.root.expand()
        self._build_tree()

    def _build_tree(self) -> None:
        self.root.remove_children()
        chain = self._tt_config.resolve_chain(self._host)
        parent_node = self.root
        for cfg in chain:
            pkg_count = len(
                self._tt_config.get_packages(cfg, "brew")
            ) + len(
                self._tt_config.get_packages(cfg, "apt")
            )
            file_count = len(self._tt_config.get_file_mappings(cfg))
            label = f"{cfg}  ({pkg_count} pkg, {file_count} files)"
            if cfg == chain[-1]:
                parent_node = parent_node.add_leaf(label)
            else:
                parent_node = parent_node.add(label)
                parent_node.expand()
