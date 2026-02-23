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

    `apt` is used by default. For dependency-aware uninstalls, install `apt-rdepends`:

    ```bash
    sudo apt install apt-rdepends
    ```

=== "Linux (Arch)"

    `pacman` is supported but not heavily tested yet.

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
