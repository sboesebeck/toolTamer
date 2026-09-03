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

### `files.conf`

Maps files in the `files/` subdirectory to their target location relative to `$HOME`.

```
# Format: filename;target_relative_to_home
myzshrc;.zshrc
myKittyConf;.config/kitty/kitty.conf
shellScript;bin/
```

- If the target ends with `/`, the file keeps its original name and is placed in that directory.
- Comparison uses **SHA256 checksums** — if checksums differ, ToolTamer asks what to do.

### Git repositories

`files.conf` is unchanged for this case — the entry is still a directory
mapping like any other. What changes is what's *inside* the entry's
`files/` directory: instead of a mirrored copy of the directory's
contents, it holds only a `.ttgit` marker file. ToolTamer never stores the
repository's contents and never mirrors it; it syncs the entry with `git
clone` / `git pull` instead.

```
configs/<host>/files.conf
  nvim;.config/nvim

configs/<host>/files/nvim/.ttgit
  url    = git@github.com:you/nvim.git
  branch = main
  force  = false
```

| Key | Required | Default | Meaning |
|---|---|---|---|
| `url` | yes | — | remote URL, used as `origin` |
| `branch` | no | remote HEAD | branch to check out |
| `force` | no | `false` | `true` allows a hard reset to the remote |

Everything from the first `#` in a line is a comment, so values must not
contain `#` — but they may contain `=` (only the first `=` on a line
separates key from value). Key names are case-sensitive and must be
exactly `url`, `branch`, `force`; unknown keys are ignored. If a key
appears more than once, the last occurrence wins.

**Syncing a repo entry (ToolTamer → system):**

| Situation | Result |
|---|---|
| not present on the system yet | cloned |
| present, but not a git repository | the existing path is moved aside to `<path>.ttbak`, then cloned |
| present, clean, behind the remote | fast-forward pulled |
| present, clean, up to date | left alone |
| local commits not yet pushed | left alone — ToolTamer never pushes |
| uncommitted changes or diverged history, `force = false` (default) | left alone, reported |
| uncommitted changes or diverged history, `force = true` | hard-reset and cleaned to match `origin/<branch>` |
| `origin` on the system points somewhere else than `url` | skipped, reported |
| remote unreachable (`git fetch` fails) | skipped for this run, reported; the rest of the sync continues |
| `.ttgit` has no `url` | reported as a broken entry, sync skipped |

`force = true` only ever authorizes that one hard-reset-and-clean step,
for a repo that is dirty or has diverged from its remote branch — it
changes nothing about the clone-vs-pull decision otherwise, and it never
makes ToolTamer push. Leave it `false` (the default) for any repository
you edit locally; set it only for ones you never touch by hand.

Saving a repo entry (system → ToolTamer, the `u` key in the file manager)
never captures file contents — it only refreshes `url` and `branch` in
the marker from the system's current git remote and checked-out branch,
and only writes the marker back when one of them actually changed.

ToolTamer does not push, does not pin commits, and does not handle
submodules. A repository with uncommitted changes or a history that has
diverged from the remote is skipped, not merged — you resolve it by hand,
in the repository itself.

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

## Global Settings

ToolTamer's own settings are in `~/.config/toolTamer/tt.conf`:

```bash
GIT_AUTO_UPDATE=ask    # true | false | ask — auto git-pull on start
```
