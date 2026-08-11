# Configuration

All configuration lives in `~/.config/toolTamer/configs/`. ToolTamer uses your machine's **hostname** to find the right config directory.

## Directory Structure

```
~/.config/toolTamer/configs/
├── common/              # Base config — inherited by ALL hosts
│   ├── to_install.brew
│   ├── to_install.apt
│   ├── files.conf
│   └── files/
├── common_mac/          # Optional macOS-specific base
│   ├── to_install.brew
│   ├── local_install.sh
│   ├── files.conf
│   └── files/
└── myMacBook/           # Host-specific config
    ├── includes.conf
    ├── to_install.brew
    ├── local_install.sh
    ├── taps
    ├── files.conf
    └── files/
```

## Configuration Hierarchy

ToolTamer resolves configs in this order:

1. **`common/`** — always included for every host
2. **Configs listed in `includes.conf`** — additional layers (e.g. `common_mac`)
3. **Host directory** — your machine's hostname

When the same file or package appears in multiple layers, **the more specific layer wins**: host overrides includes, includes override common.

!!! warning "Includes are not recursive"
    If an included config has its own `includes.conf`, it is **ignored**. Only the host's `includes.conf` is processed.

## Configuration Files

### `to_install.brew` / `to_install.apt` / `to_install.pacman`

One package name per line. Comments start with `#`.

```
# Terminal tools
fzf
ripgrep
lazygit
# Development
node
python3
```

ToolTamer ensures **exactly** these packages are installed. Packages present on the system but **not** in any config file will be offered for removal (dependencies are preserved).

!!! tip "Packages from third-party taps need their full name"

    List a tapped Homebrew package fully qualified —
    `forketyfork/tap/clawtunes`, not `clawtunes`. The short name only
    resolves on a machine where that tap has already been added, so it makes
    the package uninstallable on a fresh host; `brew install user/repo/formula`
    adds the tap by itself. Adding a package through the TUI does this
    automatically, and `tt --fix-taps` fixes existing entries.

!!! note "What counts as a dependency"

    A package is kept when another *installed* package actually requires it —
    ToolTamer asks the package manager, it does not guess from the name. That
    answer is cached per machine (see `cache/` below), so only the first run
    after installing or removing something pays for the lookup.

    Note this is a different question from "was it installed automatically".
    A package you installed by hand can still be required by something else,
    and is then kept.

### `files.conf`

Maps files in the `files/` subdirectory to their target location relative to `$HOME`.

```
# Format: filename:target_relative_to_home
myzshrc:.zshrc
myKittyConf:.config/kitty/kitty.conf
shellScript:bin/
```

- If the target ends with `/`, the file keeps its original name and is placed in that directory.
- Comparison uses **SHA256 checksums** — if checksums differ, ToolTamer asks what to do.

### `includes.conf`

A simple list of config directory names to include, one per line:

```
common_mac
dev_tools
```

### `local_install.sh`

An optional shell script executed every time `tt --syncSys` (or "Update System") runs. Scripts are executed in order: common → includes → host.

Use this for installations that can't be handled by the package manager (e.g. manual downloads, pip installs, font installations).

### `taps` (macOS only)

A list of Homebrew taps, one per line:

```
homebrew/cask-fonts
hashicorp/tap
```

These are added before packages are installed. Note that a package listed
under its fully qualified name (`hashicorp/tap/terraform`) does not need an
entry here — brew adds the tap on its own — but listing taps is still useful
for casks and for taps you want present regardless.

## Generated files

Next to `configs/` there is a `cache/` directory holding machine-local data,
currently the reverse-dependency lookups that keep repeated runs fast. It is
regenerated automatically whenever your installed packages change.

Add `cache/` to your config repo's `.gitignore` — it is specific to one
machine and has no business being shared.

## Global Settings

ToolTamer's own settings are in `~/.config/toolTamer/tt.conf`:

```bash
GIT_AUTO_UPDATE=ask    # true | false | ask — auto git-pull on start
```
