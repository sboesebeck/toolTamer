# Installation

## Prerequisites

- **Operating System**: Linux or macOS
- **Git**: required for managing your configuration repository

### Package Manager

=== "macOS"

    [Homebrew](https://brew.sh/) must be installed:

    ```bash
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    ```

=== "Linux (Debian/Ubuntu)"

    `apt` is used by default. Nothing extra to install — dependency-aware
    uninstalls use `apt-cache`, which ships with apt itself.

=== "Linux (Arch)"

    `pacman` is supported but not heavily tested yet. Uninstalling is not
    implemented for pacman; unlisted packages are reported but left alone.

### Python (for the TUI and the helper tools)

**Python 3.12+** is required for the interactive TUI and the `--fix-taps` /
`--cleanup-deps` tools. `tt` sets up its own virtual environment on first
use, so there is nothing to install by hand. Without a suitable Python,
`tt` cannot start its interface and the helper tools are unavailable.

### Optional Tools

- **fzf** — enables interactive fuzzy-search menus (falls back to numbered menus otherwise)
- **lazygit** — used by the Admin menu's "Git view" option

## Install ToolTamer

1. **Clone the repository:**

    ```bash
    git clone https://github.com/sboesebeck/toolTamer.git ~/toolTamer
    ```

2. **Add to your PATH** — add this line to your `.zshrc` or `.bashrc`:

    ```bash
    eval "$(~/toolTamer/bin/tt -sh)"
    ```

3. **Restart your shell** or source the file:

    ```bash
    source ~/.zshrc
    ```

4. **Verify:**

    ```bash
    tt -h
    ```
