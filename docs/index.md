# ToolTamer

**Cross-platform system configuration and package synchronization.**

ToolTamer is a Bash tool that automates installation, synchronization, and cleanup of tools and configuration files across multiple systems. It uses your existing package manager — **Homebrew** on macOS, **apt** or **pacman** on Linux — and stores everything in a Git-backed configuration repository.

## Why ToolTamer?

Managing dotfiles across machines is a solved problem — until you also need to keep your installed packages in sync. Most solutions handle only one side:

- **Dotfile managers** (chezmoi, stow, yadm) sync config files but don't manage packages.
- **Nix/Home Manager** does both but is slow, hard to maintain, and breaks after macOS updates when combined with nix-darwin.

ToolTamer handles both: it installs missing packages, removes unlisted ones, and synchronizes your configuration files — all driven by simple text files in a Git repo.

## Key Features

- **Automated package management** — installs missing tools, removes unlisted ones to prevent system clutter.
- **Configuration file sync** — manages dotfiles and config files using SHA256 checksum comparison.
- **Cross-platform** — works on macOS (Homebrew), Linux (apt, pacman).
- **Hierarchical configuration** — common base config inherited by all hosts, with host-specific overrides.
- **Git-backed** — your entire configuration lives in a Git repo, shareable across machines.
- **Interactive menus** — fzf-powered menus with fallback to numbered selection.
- **Dependency-aware** — won't accidentally uninstall packages that are dependencies of others.

## Quick Overview

```
~/.config/toolTamer/configs/
├── common/          # Shared across all machines
├── common_mac/      # macOS-specific base
└── myMacBook/       # Host-specific config
    ├── includes.conf
    ├── to_install.brew
    ├── files.conf
    └── files/
```

Run `tt` to get an interactive menu, or use CLI flags for automation:

```bash
tt --syncSys              # Apply config to system
tt --updateToolTamer      # Snapshot system into config
tt --admin                # Advanced management
```

## Getting Started

Head to [Installation](installation.md) to set up ToolTamer, then follow the [Getting Started](getting-started.md) guide for your first sync.
