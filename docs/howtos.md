# How-Tos

These describe the TUI, which is what `tt` opens. Every screen lists its
keys in the footer, so you never have to remember them.

## Add a config file to ToolTamer

You have a config file (e.g. `~/.config/starship.toml`) that you want to manage with ToolTamer.

1. `tt` → **File Manager** (`d`)
2. Press `n` to add a file. With `fzf` installed you get a fuzzy picker over your home directory; otherwise a directory browser opens.
3. Choose the target config (your host, `common`, or a shared one)

ToolTamer copies the file into that config's `files/` directory and adds the mapping to `files.conf`.

**Or manually:**

1. Copy the file:
    ```bash
    cp ~/.config/starship.toml ~/.config/toolTamer/configs/common/files/starship.toml
    ```
2. Add to `files.conf`:
    ```
    starship.toml:.config/starship.toml
    ```

**Or from the shell**, without opening the TUI:

```bash
tt --add ~/.config/starship.toml
```

## Move a config file between configs

You have a file in your host config that should be shared via `common`:

1. `tt` → **File Manager** (`d`)
2. Select the file, press `m`
3. Pick the target config

ToolTamer moves the stored copy and updates both `files.conf` entries.

## Move a package between configs

A package is listed in your host's `to_install.brew` but should be in `common`:

1. `tt` → **Package Manager** (`p`)
2. Select the package, press `m` (or `c` to copy instead of move)
3. Pick the target config

To move several at once, mark them with `Space` first — `m` then applies to
the whole selection and asks once for the destination.

## Install or remove packages

In the **Package Manager** (`p`), the status column tells you where each
package stands:

| Status | Meaning |
|--------|---------|
| `OK` | in a config and installed |
| `!!` | in a config but missing on this machine |
| `++` | installed but in no config |
| `D`  | required by another installed package |

| Key | Action |
|-----|--------|
| `i` | install the selected package |
| `x` | uninstall it from the system |
| `a` | add it to a config |
| `r` | remove it from its config (leaves it installed) |
| `u` | uninstall **and** remove from the config |
| `d` | hide/show dependency-only packages |
| `Space` | mark a row — `x`, `m`, `r` and `u` then act on all marked rows |
| `/` | filter (also accepts a status: `!!`, `OK`, `++`) |

Uninstalling is checked against the real dependency graph first: if another
installed package still needs it, the removal is refused and tells you what
depends on it, rather than failing halfway through.

For bulk actions you get a preview listing what will be processed and what is
skipped (with the reason) before anything happens.

## View what's different

### File differences

`tt` → **File Manager** (`d`). Each tracked file shows its status, and
selecting one shows a diff against what's actually on disk:

| Status | Meaning |
|--------|---------|
| `OK` | identical |
| `!!` | differs |
| `--` | missing on the system |
| `<<` | shadowed by another config |
| `==` | duplicate within the same config |

Then choose per file:

- `a` — apply the ToolTamer version to the system (overwrites the local file)
- `u` — save the local change into ToolTamer. For inherited files you are
  asked whether it should go into the shared config (affecting all hosts) or
  become a host-local override.
- `r` — stop managing the file (leaves it on the system)

Directories are supported and diffed recursively; before a sync that would
delete files on the destination, you get an explicit confirmation listing them.

### Package differences

`tt` → **Package Manager** (`p`) — see the table above. Filter with `/` to see
only one category, e.g. `!!` for everything missing.

## Manage Homebrew taps

`tt` → **Tap Manager** (`t`, macOS only):

| Key | Action |
|-----|--------|
| `a` | add a tap to a config |
| `r` | remove a tap from a config |
| `m` | move a tap to another config |
| `t` / `u` | tap / untap on this machine |
| `s` | sync all configured taps |

Note that a package listed under its fully qualified name
(`forketyfork/tap/clawtunes`) does not need a tap entry — brew adds the tap
itself. See [Configuration](configuration.md#to_installbrew-to_installapt-to_installpacman).

## Clean up the config

Two one-off audit tools, both dry-run by default:

```bash
tt --fix-taps        # rewrite tap packages to their fully qualified names
tt --cleanup-deps    # drop packages only listed because something depends on them
```

Add `--apply` to actually change anything; you get a preview and a
confirmation prompt first. `tt --cleanup-deps --keep <package>` protects
individual packages from removal.

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
4. Use **Snapshot** (`s`) to capture the current state
5. Or: create a symlink to an existing host config if the setup should be identical:
    ```bash
    cd ~/.config/toolTamer/configs
    ln -s existingHost newHostname
    ```
