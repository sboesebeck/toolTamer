# Getting Started

## First Run

Start ToolTamer:

```bash
tt
```

On first run, you'll be asked for a **Git repository URL** for your configuration. You have two options:

- **Provide a URL** — ToolTamer clones it into `~/.config/toolTamer/`.
- **Press Enter** — ToolTamer creates a default structure locally in `~/.config/toolTamer/`.

If you create a fresh config, ToolTamer will offer to seed it with common config files (like `.zshrc`, `.bashrc`, etc.) based on what exists in your home directory.

## The Main Menu

After the optional Git pull, you'll see:

```
-----> ToolTamer V1.0 - main menu
1. Update System - full system update, local files, installation, local install script
2. Files only - update only files
3. Snapshot System
4. Admin
5. Quit
```

### Update System

Applies your ToolTamer configuration to the current machine:

1. Installs packages listed in `to_install.brew` / `to_install.apt` / `to_install.pacman`
2. Removes packages that are installed but **not** in your config (dependencies are preserved)
3. Syncs configuration files from ToolTamer to your home directory
4. Runs `local_install.sh` scripts (if present)

### Files Only

Same as above, but skips package management — only syncs configuration files.

### Snapshot System

The reverse direction: captures your current system state into ToolTamer:

- Records all installed packages into the `to_install.*` file
- Copies current versions of configured files into ToolTamer

This is useful when you've set up a new machine manually and want to capture that state.

## Typical Workflow

1. **Set up your first machine:**
    - Install ToolTamer
    - Run `tt`, let it create a default config
    - Customize your package list and add config files
    - Use "Snapshot System" to capture your setup

2. **Push your config:**
    - Open Admin → Git view (lazygit) to commit and push

3. **Set up another machine:**
    - Install ToolTamer
    - Run `tt`, provide your Git repo URL
    - Use "Update System" to apply the config

4. **Ongoing sync:**
    - Make changes on any machine
    - Snapshot → commit → push
    - Pull → Update System on other machines
