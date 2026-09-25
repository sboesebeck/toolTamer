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
# Format: filename;target_relative_to_home
myzshrc;.zshrc
myKittyConf;.config/kitty/kitty.conf
shellScript;bin/
```

- If the target ends with `/`, the file keeps its original name and is placed in that directory.
- Comparison uses **SHA256 checksums** — if checksums differ, ToolTamer asks what to do.

### Ignoring files inside a tracked directory (`.gitignore` / `.ttignore`)

A tracked directory is mirrored as a whole, but you can carve entries out
of it. ToolTamer reads `.gitignore` and `.ttignore` files anywhere inside a
tracked directory — no git repository required — and treats everything they
match as **invisible**:

- it is not copied into the store when the directory is added,
- it is not written to the system and not deleted from it on sync,
- it is not hashed, so changing it does not mark the entry as *modified*.

The matching follows real gitignore rules (`pathspec.GitIgnoreSpec`):
anchors (`/x`), `**`, `!` negation, trailing-slash directory patterns and
nested ignore files all work. In each directory `.gitignore` is read first,
then `.ttignore`, so a later `.ttignore` rule wins and can re-include
something with `!`. Deeper directories win over shallower ones.

`.gitignore` and `.ttignore` are ordinary files: they are synced along with
everything else, so after a sync both sides normally hold the same rules.

The **system directory is authoritative** (like the worktree is for git):
ToolTamer takes the rules from the system copy when it exists, and from the
store only when there is no system copy yet.

!!! note "New files on the system"

    When you apply (`a`) or capture (`u`) a directory and the system side
    has files the store does not know, the TUI asks per file whether to
    **adopt** it (keep it, copy it across) or **ignore** it (write an
    anchored `/<path>` line into `.ttignore` on both sides). Selected
    (checked) rows are adopted; ignore them with the space key, `n` for all,
    `a` to adopt all, Esc cancels the whole sync. Previously those files
    were silently deleted (apply) or silently absorbed (capture).

    The scripted sync (`tt --syncFilesOnly`, and the whole "Update System"
    run) has no dialog — it just honours the ignore rules that are already
    there. Ignore patterns are computed by one engine
    (`tui/core/ignore.py`, exposed to the Bash mirror as
    `python3 -m tui.ttignore`), so the TUI and the CLI always agree.

    You can also ignore existing files on purpose: in the file manager,
    press **`i`** on a tracked directory and pick files from the list. They
    get an anchored rule on both sides and drop out of the sync — the
    counterpart of **`s`**, which encrypts instead of hiding.

    This needs `pathspec`. In the normal `.venv` setup it is installed
    already. If a tracked directory carries ignore files but no usable
    engine is available, ToolTamer refuses that directory's mirror rather
    than mirroring without the filter — nothing gets deleted.

### Git repositories

> **Update ToolTamer on every machine before you create your first repo
> entry.** `files.conf` is deliberately left unchanged by this feature so
> that old and new versions of `tt` can read the same store — but the
> *store itself* syncs between your machines, and a machine still running
> an older `tt` does not know what a `.ttgit` marker is. It sees the marker
> directory as an ordinary tracked directory and mirrors it onto the
> system: the marker is copied in, and everything else in the target —
> including the repository's `.git` directory and any uncommitted work — is
> deleted as "extra". That is exactly the loss this feature exists to
> prevent, and no version of `tt` can stop it from the far side. Pull and
> install the current ToolTamer on every host that shares this config
> first; only then convert or add the first repo entry.

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
| a branch other than `branch` is checked out | skipped, reported — both branches are named |
| `origin` on the system points somewhere else than `url` | skipped, reported |
| remote unreachable (`git fetch` fails) | skipped for this run, reported; the rest of the sync continues |
| `.ttgit` has no `url` | reported as a broken entry, sync skipped |

`force = true` only ever authorizes that one hard-reset-and-clean step,
for a repo that is dirty or has diverged from its remote branch — it
changes nothing about the clone-vs-pull decision otherwise, and it never
makes ToolTamer push. Leave it `false` (the default) for any repository
you edit locally; set it only for ones you never touch by hand.

ToolTamer never checks out `branch` for you. If the repository is sitting
on some other branch — or on a detached HEAD — the entry is skipped and
reported as a branch mismatch, naming both the checked-out branch and the
one in the marker. That is deliberate: pulling or resetting would act on
the branch you are standing on, not the one the marker names, and with
`force = true` that would discard commits the marker never referred to.
Check the marker's branch out yourself, or press `u` to record the branch
you are actually on.

Saving a repo entry (system → ToolTamer, the `u` key in the file manager)
never captures file contents — it only refreshes `url` and `branch` in
the marker from the system's current git remote and checked-out branch,
and only writes the marker back when one of them actually changed.

ToolTamer does not push, does not pin commits, and does not handle
submodules. A repository with uncommitted changes or a history that has
diverged from the remote is skipped, not merged — you resolve it by hand,
in the repository itself.

### Secrets (encrypted entries)

The store is one git repo that every machine clones in full, so anything
committed to it is on every machine. Put ssh keys, tokens, `.netrc` and
similar material in `secrets.conf` instead of `files.conf` — those entries
are stored **encrypted** (age), and a machine can only decrypt the ones it
is entitled to.

```conf
# configs/common/secrets.conf
# stored;target[;scope]   — same layout as files.conf, scope defaults to
#                           the config the entry lives in
id_ed25519;.ssh/id_ed25519
work_token;.config/work/token
```

A **scope** is a config name, so entitlement follows the include hierarchy:
a secret in `common` reaches every machine, one in a host config only that
host, one in `common_mac` the machines that include it. Each scope has an
age keypair; the private half is stored in the repo **wrapped to the
members plus the admin key**, and secret files are encrypted to the scope's
public key. Adding a machine re-wraps that one small key — the secret files
are not touched.

Requires the `age` binary (`brew install age` / `apt install age`).

#### Bootstrapping a new machine

No private key is ever copied between machines — only public keys travel.

```bash
# first machine, once
tt --secrets init          # creates keys/<id>.key (local) and secrets/admin.pub
                           # prints the admin private key — keep it in a
                           # password manager, off the repo

# new machine: clone the config repo, then
tt --secrets init          # registers this machine's public key
tt --secrets join --admin-key <recovery key>   # becomes a member of its scopes

# move existing plaintext files into encrypted storage
tt --secrets migrate        # dry run; --apply to encrypt
tt --secrets check          # fails if a secret entry is plaintext
tt --secrets status         # scopes, members, entries
```

`join` needs the admin/recovery key once (a paste from your password
manager). A machine that is *not* a member of a scope and holds no admin
key cannot decrypt it — that is the isolation. Remove a machine with
`tt --secrets rotate <scope>` (new scope key + re-encrypt its files).

#### How sync treats a secret

- **TT → system**: decrypt, write, `chmod 600`.
- **system → TT**: encrypt; only rewritten when the plaintext actually
  changed (age output is non-deterministic).
- Comparisons and diffs use the decrypted plaintext, never the ciphertext.
- In the file manager secrets show with an `S` token and a lock; `a` applies
  (decrypts), `u` saves (encrypts), `s` encrypts an existing plaintext entry.
- Bash delegates all crypto to `python -m tui.secrets`, so there is a single
  implementation; the encrypt/decrypt path needs only Python + `age`.

Private keys (`keys/`) are added to the store's `.gitignore` automatically,
like `machine-id`.

#### Files inside a tracked directory

A whole tracked directory does not have to be encrypted to protect one file
in it (e.g. `~/.config/opencode/opencode.json` next to many non-secret
files). Such a file can be **carved out**:

```bash
tt --secrets migrate --apply .config/opencode/opencode.json
```

The file is encrypted and recorded as its own secret entry, while an
anchored rule (`/opencode.json`) is written to `.ttignore` on both sides so
the directory mirror leaves it alone — the two engines never fight over it,
and no mirror code had to change. The rest of the directory keeps syncing
(and diffing) as plaintext.

In the file manager, `s` on a directory opens a picker of its visible files
to encrypt; `tt --secrets unmark <path>` decrypts one back into the
directory mirror.

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
