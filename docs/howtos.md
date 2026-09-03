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
    starship.toml;.config/starship.toml
    ```

## Track a git repository instead of copying it

You have a directory under `~` that is itself a git repository (e.g.
`~/.config/nvim`) and want ToolTamer to keep it up to date via `git
clone`/`git pull` instead of mirroring its files — and its `.git`
directory — into the ToolTamer store.

**Do this first: update ToolTamer on every machine that shares this
config.** The config store travels between your machines on its own, and a
machine still running an older `tt` does not recognise a `.ttgit` marker.
It treats the marker directory as a plain tracked directory and mirrors it
over the repository on that machine — copying the marker in and deleting
everything else, `.git` and uncommitted work included. Nothing on the new
side can prevent that, so bring every host up to date before you create
your first repo entry.

1. Open `tt` (or `tt --admin`) → **File Manager**, then press `n` and pick
   the repository's root directory. With `fzf` installed you get a fuzzy
   picker over everything under `~` (faster when `fd` is also installed);
   without `fzf`, a directory-tree browser.
2. ToolTamer detects that the path is the root of a git repository (with
   an `origin` remote) and asks whether to **track as repo** or **copy
   contents**. Picking a plain file, or a directory that is not itself a
   repo root, skips this and adds it normally.
3. Choose **Track as repo**. ToolTamer records the detected `origin` URL
   and current branch in a `.ttgit` marker and adds the usual `files.conf`
   entry — the store then holds only that marker, never the repository's
   contents.

From then on, `a` (apply TT → system) clones the repository where it's
missing and fast-forwards it where it's behind; `u` (save) only ever
refreshes the marker's `url`/`branch` from the system, never its content.
See [Git repositories](configuration.md#git-repositories) for the full
sync behavior and its limits.

## Convert an already-tracked directory into a repo entry

You already copy a directory into ToolTamer the normal way, and only
later turned it into (or noticed it already is) a git repository on your
system.

The same warning applies here as above: every machine sharing this config
needs the current `tt` **before** you convert an entry, or an old `tt` on
another host will mirror the marker directory over your repository and
delete its contents.

1. Select the entry in the file manager and press `g`. This is only
   offered when the tracked entry is a directory, is not already a repo
   entry, and `~/<target>` on your system is currently the root of a git
   repository.
2. A confirmation dialog shows the detected `origin` URL and branch, and
   how many stored files will be removed from the ToolTamer store once
   the entry becomes a marker-only repo entry. Your system copy is never
   touched by this step.
3. Confirm with `y`. ToolTamer deletes the entry's stored content and
   writes a `.ttgit` marker in its place; `files.conf` itself does not
   change.

If a tracked directory's system side is detected as a git repository root
but hasn't been converted, the detail pane says so and reminds you that
`g` will do it.

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

Shows packages that are missing (in config but not installed) or excess (installed but not in config). Use TAB to multi-select, then:

| Key | Action |
|-----|--------|
| **F1** | Install selected missing packages |
| **F3** | Remove selected excess packages from system |
| **F5** | Add selected excess packages to ToolTamer config |
| **F7** | Remove selected missing packages from ToolTamer config |

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
