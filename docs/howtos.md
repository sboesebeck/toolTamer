# How-Tos

## Add a config file to ToolTamer

You have a config file (e.g. `~/.config/starship.toml`) that you want to manage with ToolTamer.

1. Open `tt --admin` → **"Move local file to ToolTamer"**
2. Select the target config (your host or `common`)
3. Enter the path to the file
4. ToolTamer copies it to the `files/` directory and adds the mapping to `files.conf`

**Or manually:**

1. Copy the file:
    ```bash
    cp ~/.config/starship.toml ~/.config/toolTamer/configs/common/files/starship.toml
    ```
2. Add to `files.conf`:
    ```
    starship.toml:.config/starship.toml
    ```

## Move a config file between configs

You have a file in your host config that should be shared via `common`:

1. Open `tt --admin` → **"Move files between configs in ToolTamer"**
2. Select source config, then target config
3. Select the file to move

ToolTamer moves the file and updates both `files.conf` entries.

## Move a package between configs

A package is listed in your host's `to_install.brew` but should be in `common`:

1. Open `tt --admin` → **"View differences of installed tools"**
2. Or manually: remove the line from your host's file and add it to `common/to_install.brew`

## Fix duplicate packages

When including multiple configs, the same package may be listed in several places. This is harmless but messy:

1. Open `tt --admin` → **"Fix duplicate packages"**
2. ToolTamer removes packages from your host config that are already covered by included configs

## View what's different

### File differences

`tt --admin` → **"View differences of files"**

Shows a diff for each configured file where the ToolTamer version and the system version differ. For each difference, you choose:

- **Take system version** — update ToolTamer with the local change
- **Restore ToolTamer version** — overwrite the local file
- **Skip** — do nothing

### Package differences

`tt --admin` → **"View differences of installed tools"**

Shows packages that would be installed or removed. You can decide for each.

## Use ToolTamer without interaction

For scripting or cron jobs:

```bash
tt --syncSys            # Full sync (packages + files + local_install.sh)
tt --syncFilesOnly      # Only sync files
tt --updateToolTamer    # Snapshot packages
tt --updateToolTamerFiles  # Snapshot packages + files
```

## Set up a shared config for multiple Macs

1. Create `common_mac/` with shared macOS packages and configs
2. In each Mac's `includes.conf`, add:
    ```
    common_mac
    ```
3. Put Mac-specific overrides (like different Homebrew taps) in the host directory

## Create a config for a new machine

1. Install ToolTamer on the new machine
2. Run `tt` — provide your Git repo URL
3. ToolTamer creates a host directory based on the hostname
4. Use "Snapshot System" to capture the current state
5. Or: create a symlink to an existing host config if the setup should be identical:
    ```bash
    cd ~/.config/toolTamer/configs
    ln -s existingHost newHostname
    ```
