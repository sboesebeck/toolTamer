trap cleanup EXIT QUIT TERM

GN='\033[0;32m'
RD='\033[0;31m'
BL='\033[0;34m'
YL='\033[0;33m'
MG='\033[0;35m'
CN='\033[0;36m'

RESET="\033[0m"

ERR=$RD
WR=$YL
export BASE=$HOME/.config/toolTamer/

if command -v fzf >/dev/null 2>&1; then
  HAVE_FZF=1
else
  HAVE_FZF=0
fi

function cleanup() {
  echo "Cleaning up"
  rm -rf $TMP
}

function logn() {
  echo -ne "$1"
}
function log() {
  echo -e "$1"
}

function err() {
  echo -e "${ERR}error:$RESET $1"
}

function warn() {
  echo -e "${WR}Warning:$RESET $1"
}

function logf() {
  echo -e "$1" >>$TMP/log
}

# Record a change for the end-of-run summary: note "<category>" "<detail>"
# Written to a file because the sync loops run in subshells where
# variables would not survive.
function note() {
  echo "$1;$2" >>$TMP/summary
}

# Print all recorded changes grouped by category, then reset the record
# so the next action in the menu loop starts with a clean slate.
function printSummary() {
  echo
  log "---------> ${CN}Summary of changes$RESET <-----------"
  if [ ! -s "$TMP/summary" ]; then
    log "${GN}No changes${RESET} - everything was already in sync."
    echo
    return
  fi
  cut -f1 -d';' "$TMP/summary" | awk '!seen[$0]++' | while IFS= read -r category; do
    cnt=$(grep -c "^$category;" "$TMP/summary")
    log "${BL}$category$RESET ($cnt):"
    grep "^$category;" "$TMP/summary" | cut -f2- -d';' | sed 's/^/    /'
  done
  echo
  : >"$TMP/summary"
}

function fzf_available() {
  [ "${HAVE_FZF:-0}" -eq 1 ]
}

function fzf_themed() {
  fzf \
    --ansi \
    --border=rounded \
    --pointer="▶" \
    --marker="✓" \
    --highlight-line \
    --color="header:blue,border:cyan,pointer:yellow,marker:green" \
    "$@"
}

function createEffectiveFilesList() {
  echo >$1

  for i in common $(<$BASE/configs/$HOST/includes.conf) $HOST; do
    log "Processing files from config: ${BL}$i$RESET"
    cat $BASE/configs/$i/files.conf | while read l; do
      f=$(echo $l | cut -f1 -d\;)
      d=$(echo $l | cut -f2 -d\;)
      if [ -z "$f" ]; then
        continue
      fi
      if [[ "$f" =~ "#" ]]; then
        continue
      fi
      #log "Syncing file $f with ~/$d"
      if [ "$d" != "${d%/}" ]; then
        #ends with /
        d=$d$(basename "$f")
      fi
      if grep ";$HOME/$d" $1 >/dev/null; then
        grep -v ";$HOME/$d" $1 >$1.tmp || {
          err "error"
          exit 1
        }
        mv $1.tmp $1
      fi
      echo "$BASE/configs/$i/files/$f;$HOME/$d" >>$1
    done
  done
}

# Content hash of a directory tree (all regular files + symlinks, path-stable).
# Prints "missing" for non-directories so comparisons always differ.
function treeHash() {
  local dir="$1"
  if [ ! -d "$dir" ]; then
    echo "missing"
    return 1
  fi
  (
    cd "$dir" || exit 1
    find . \( -type f -o -type l \) -print0 2>/dev/null | sort -z | while IFS= read -r -d '' f; do
      if [ -L "$f" ]; then
        printf 'link %s -> %s\n' "$f" "$(readlink "$f")"
      else
        printf '%s %s\n' "$(shasum <"$f" | cut -f1 -d' ')" "$f"
      fi
    done
  ) | shasum | cut -f1 -d' '
}

# Print relative paths that exist in $2 (dest) but not in $1 (src) —
# the files a mirror operation would delete on the destination.
function listDirExtras() {
  local src="$1"
  local dst="$2"
  [ -d "$dst" ] || return 0
  (cd "$dst" && find . \( -type f -o -type l \) 2>/dev/null | sed 's|^\./||') | while IFS= read -r f; do
    [ -z "$f" ] && continue
    if [ ! -e "$src/$f" ] && [ ! -L "$src/$f" ]; then
      echo "$f"
    fi
  done
}

# True when every file/directory under $1 can be enumerated: readable
# and searchable at its own top level AND with no permission error
# anywhere further down. A directory can pass a plain [-r]/[-x] check on
# itself while still containing an unreadable subdirectory — `find`
# then silently omits that subtree instead of failing outright, which is
# exactly what let listDirExtras see a mirror destination's counterparts
# under it as "extra" and delete them. mirrorDir and its two callers
# (syncDirToSystem, captureDirFromSystem) all use this one predicate so
# a bad subdirectory is reported once, as a clean skip, rather than
# falling through to a confusing partial failure further down.
function dirFullyReadable() {
  local dir="$1"
  [ -r "$dir" ] && [ -x "$dir" ] || return 1
  local enum_err
  enum_err=$(cd "$dir" && find . \( -type f -o -type l \) 2>&1 >/dev/null)
  [ -z "$enum_err" ]
}

# Mirror directory $1 into $2: full copy including deletion of files that
# are not present in the source. Uses rsync when available.
#
# Refuses to run at all when $1 cannot be fully read (see
# dirFullyReadable): the manual fallback below builds its file list from
# `find "$src"`, which silently omits whatever it cannot read, and
# listDirExtras would then see every missing file in $dst as "extra" and
# delete it. That is true for ANY tracked directory, not only repo
# entries, so the guard lives here rather than in a caller.
function mirrorDir() {
  local src="$1"
  local dst="$2"
  if ! dirFullyReadable "$src"; then
    warn "$src could not be fully read - refusing to mirror (would empty $dst)"
    return 1
  fi

  mkdir -p "$dst" || return 1
  if command -v rsync >/dev/null 2>&1; then
    if rsync -a --delete "$src/" "$dst/"; then
      return 0
    fi
    # rsync is installed and ran, so a nonzero exit here is a real
    # failure (not the "rsync unavailable" case above) - falling back to
    # the manual mirror below on a partial/failed run is exactly how a
    # rsync-side problem used to turn into a manual-mirror deletion pass.
    warn "rsync failed while mirroring $src -> $dst - refusing (a partial run must not delete anything on $dst)"
    return 1
  fi
  (cd "$src" && find . \( -type f -o -type l \) 2>/dev/null | sed 's|^\./||') | while IFS= read -r f; do
    [ -z "$f" ] && continue
    mkdir -p "$dst/$(dirname "$f")"
    if [ -L "$src/$f" ]; then
      ln -sfn "$(readlink "$src/$f")" "$dst/$f"
    else
      cp -p "$src/$f" "$dst/$f"
    fi
  done
  listDirExtras "$src" "$dst" | while IFS= read -r f; do
    rm -f "$dst/$f"
  done
  find "$dst" -mindepth 1 -depth -type d -empty -delete 2>/dev/null
  return 0
}

# Sync a tracked directory from the TT store to the system (TT -> system).
# Performs a full mirror: extra files on the system side are deleted.
function syncDirToSystem() {
  local gitdir="$1"
  local sysdir="$2"
  logn "Comparing dir ${GN}$sysdir${RESET} <-> ${BL}${gitdir##$BASE/configs/}${RESET}....."
  if ! dirFullyReadable "$gitdir"; then
    log "${RD}not readable${RESET} - skipped"
    warn "$gitdir could not be fully read - $sysdir left untouched"
    note "Skipped directory sync (unreadable source)" "$sysdir"
    return
  fi
  if [ -e "$sysdir" ] && [ ! -d "$sysdir" ]; then
    log "${YL}target exists as file${RESET} - backing up, replacing with directory"
    rm -rf "$sysdir.ttbak"
    mv "$sysdir" "$sysdir.ttbak"
  fi
  if [ -d "$sysdir" ] && [ "$(treeHash "$gitdir")" = "$(treeHash "$sysdir")" ]; then
    log "${GN}Ok${RESET}"
    return
  fi
  log "${YL}directories differ...${RESET} - mirroring (incl. deletions)"
  local extra
  while IFS= read -r extra; do
    [ -z "$extra" ] && continue
    log "  ${RD}deleting$RESET $sysdir/$extra (not in ToolTamer)"
    logf "dir-sync: deleted $sysdir/$extra"
    note "Deleted file (dir sync)" "$sysdir/$extra"
  done < <(listDirExtras "$gitdir" "$sysdir")
  mkdir -p "$(dirname "$sysdir")"
  if mirrorDir "$gitdir" "$sysdir"; then
    note "Updated directory" "$sysdir"
  else
    err "Directory sync failed for $sysdir"
    note "Failed directory sync" "$sysdir"
  fi
}

# Capture a system directory into the TT store (system -> TT).
# Performs a full mirror: files removed on the system are removed in TT too.
function captureDirFromSystem() {
  local sysdir="$1"
  local gitdir="$2"
  if isRepoEntry "$gitdir"; then
    # Repo entries hold a marker, not content — mirroring would destroy it.
    captureRepoFromSystem "$sysdir" "$gitdir"
    return $?
  fi
  if ! dirFullyReadable "$sysdir"; then
    warn "$sysdir could not be fully read - $gitdir left untouched"
    note "Skipped directory capture (unreadable source)" "$sysdir"
    return 2
  fi
  if [ -e "$gitdir" ] && [ ! -d "$gitdir" ]; then
    rm -f "$gitdir"
  fi
  if [ -d "$gitdir" ] && [ "$(treeHash "$sysdir")" = "$(treeHash "$gitdir")" ]; then
    return 1
  fi
  local extra
  while IFS= read -r extra; do
    [ -z "$extra" ] && continue
    logf "capture: removed ${gitdir##$BASE/configs/}/$extra (deleted on system)"
  done < <(listDirExtras "$sysdir" "$gitdir")
  mkdir -p "$(dirname "$gitdir")"
  mirrorDir "$sysdir" "$gitdir" || {
    err "Capture failed for $sysdir"
    return 2
  }
  return 0
}

# --- git-repo entries -------------------------------------------------
#
# A tracked directory whose store side holds only a .ttgit marker is a
# repo entry: ToolTamer records where the repository comes from and syncs
# it with clone/pull instead of mirroring contents. See
# tui/core/repo.py for the Python side — both parsers must agree.

TTGIT_MARKER=".ttgit"

# True when the store entry $1 holds a repo marker instead of content.
# Fails CLOSED: anything that exists at the marker path — a directory, an
# unreadable file, a broken symlink — counts as a repo entry too, so it
# can never fall through to mirrorDir. readRepoSpec's own [ -f ] check
# then reports it as a broken marker (empty url) rather than mirroring.
function isRepoEntry() {
  [ -e "$1/$TTGIT_MARKER" ] || [ -L "$1/$TTGIT_MARKER" ]
}

# readRepoSpec <storedir> <key> -- prints the value, empty when unset.
# Values must not contain '#'; everything from the first '#' is a comment.
# A repeated key takes its LAST occurrence, matching tui/core/repo.py's
# read_marker (a dict keyed by name — later assignment wins).
function readRepoSpec() {
  local marker="$1/$TTGIT_MARKER"
  [ -f "$marker" ] || return 1
  sed -e 's/#.*$//' "$marker" |
    grep -E "^[[:space:]]*$2[[:space:]]*=" |
    tail -1 |
    cut -f2- -d= |
    sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

# Prints the repository root of $1, or nothing when $1 is not a repo root.
# A subdirectory of a repo prints nothing: only roots are trackable.
function ttGitTopLevel() {
  local dir="$1"
  [ -d "$dir" ] || return 1
  command -v git >/dev/null 2>&1 || return 1
  local top
  top=$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null) || return 1
  [ -n "$top" ] || return 1
  local resolved_dir resolved_top
  resolved_dir=$(cd "$dir" 2>/dev/null && pwd -P) || return 1
  resolved_top=$(cd "$top" 2>/dev/null && pwd -P) || return 1
  [ "$resolved_dir" = "$resolved_top" ] || return 1
  echo "$resolved_top"
}

# ttGitClone <url> <branch> <target>
# On failure, leaves git's stderr in $TTGIT_CLONE_ERROR (and logs it via
# logf) so callers can report the actual cause instead of a bare "failed".
function ttGitClone() {
  local url="$1" branch="$2" target="$3"
  mkdir -p "$(dirname "$target")"
  local out rc
  if [ -n "$branch" ]; then
    out=$(git clone --quiet --branch "$branch" "$url" "$target" 2>&1)
  else
    out=$(git clone --quiet "$url" "$target" 2>&1)
  fi
  rc=$?
  if [ "$rc" -ne 0 ]; then
    TTGIT_CLONE_ERROR="$out"
    logf "git clone $url -> $target failed: $out"
  else
    TTGIT_CLONE_ERROR=""
  fi
  return "$rc"
}

# Sync a repo entry from the TT store to the system (TT -> system).
# Never destroys local work unless the marker sets force = true.
function syncRepoToSystem() {
  local gitdir="$1" sysdir="$2"
  local url branch force
  url=$(readRepoSpec "$gitdir" url)
  branch=$(readRepoSpec "$gitdir" branch)
  force=$(readRepoSpec "$gitdir" force)

  logn "Comparing repo ${GN}$sysdir${RESET} <-> ${BL}${gitdir##$BASE/configs/}${RESET}....."

  if [ -z "$url" ]; then
    log "${RD}broken .ttgit${RESET} (no url)"
    note "Broken repo entry" "$sysdir (.ttgit has no url)"
    return 1
  fi
  if ! command -v git >/dev/null 2>&1; then
    log "${YL}git not installed${RESET}"
    note "Skipped repo (no git)" "$sysdir"
    return 1
  fi

  if [ ! -e "$sysdir" ]; then
    log "${YL}not cloned yet${RESET} - cloning"
    if ttGitClone "$url" "$branch" "$sysdir"; then
      note "Cloned repo" "$sysdir ($url)"
    else
      err "Clone of $url failed: ${TTGIT_CLONE_ERROR:-unknown error}"
      note "Failed repo clone" "$sysdir ($url)"
    fi
    return
  fi

  if [ -z "$(ttGitTopLevel "$sysdir")" ]; then
    log "${YL}not a git repo${RESET} - backing up, cloning"
    rm -rf "$sysdir.ttbak"
    mv "$sysdir" "$sysdir.ttbak"
    if ttGitClone "$url" "$branch" "$sysdir"; then
      note "Replaced non-repo with clone" "$sysdir (backup: $sysdir.ttbak)"
    else
      err "Clone of $url failed (backup kept at $sysdir.ttbak): ${TTGIT_CLONE_ERROR:-unknown error}"
      note "Failed repo clone" "$sysdir (backup: $sysdir.ttbak)"
    fi
    return
  fi

  local origin
  origin=$(git -C "$sysdir" remote get-url origin 2>/dev/null)
  if [ "$origin" != "$url" ]; then
    log "${RD}origin mismatch${RESET} ($origin) - skipped"
    warn "$sysdir tracks $origin but ToolTamer expects $url"
    note "Skipped repo (origin mismatch)" "$sysdir"
    return 1
  fi

  # I4: everything below compares against origin/$branch, while `pull
  # --ff-only` and `reset --hard` act on whatever branch is checked out. A
  # user on a side branch was therefore permanently reported as diverged,
  # and with force = true the reset ran on that side branch and orphaned
  # their commits. Refuse instead; checking out $branch for them would
  # discard the context they are working in without asking. Same check, same
  # position, in tui/core/repo.py's status()/sync_to_system.
  if [ -n "$branch" ]; then
    local head_branch
    head_branch=$(git -C "$sysdir" rev-parse --abbrev-ref HEAD 2>/dev/null)
    if [ "$head_branch" != "$branch" ]; then
      log "${RD}branch mismatch${RESET} ($head_branch) - skipped"
      warn "$sysdir is on branch $head_branch but .ttgit names $branch - not touched (check out $branch, or update the marker)"
      note "Skipped repo (branch mismatch)" "$sysdir"
      return 1
    fi
  fi

  if ! git -C "$sysdir" fetch --quiet origin 2>/dev/null; then
    log "${YL}remote unreachable${RESET}"
    note "Repo unreachable" "$sysdir ($url)"
    return 1
  fi

  if [ -z "$branch" ]; then
    branch=$(git -C "$sysdir" rev-parse --abbrev-ref HEAD 2>/dev/null)
  fi

  local dirty=0
  if [ -n "$(git -C "$sysdir" status --porcelain 2>/dev/null)" ]; then
    dirty=1
  fi

  local counts ahead behind
  counts=$(git -C "$sysdir" rev-list --left-right --count "HEAD...origin/$branch" 2>/dev/null)
  ahead=$(echo "$counts" | awk '{print $1+0}')
  behind=$(echo "$counts" | awk '{print $2+0}')

  if [ "$dirty" -eq 1 ] || { [ "$ahead" -gt 0 ] && [ "$behind" -gt 0 ]; }; then
    # Case-insensitive, matching tui/core/repo.py's spec.force (.lower() == "true").
    if [ "$(printf '%s' "$force" | tr '[:upper:]' '[:lower:]')" != true ]; then
      log "${YL}local changes${RESET} - skipped"
      warn "$sysdir has local changes - not touched (set force = true in .ttgit to override)"
      note "Skipped repo (local changes)" "$sysdir"
      return 1
    fi
    log "${YL}local changes${RESET} - resetting (force)"
    if git -C "$sysdir" reset --hard "origin/$branch" >/dev/null 2>&1 &&
      git -C "$sysdir" clean -fd >/dev/null 2>&1; then
      note "Reset repo to remote" "$sysdir (origin/$branch)"
    else
      err "Reset of $sysdir failed"
      note "Failed repo reset" "$sysdir"
    fi
    return
  fi

  if [ "$behind" -gt 0 ]; then
    log "${YL}behind by $behind${RESET} - pulling"
    if git -C "$sysdir" pull --quiet --ff-only >/dev/null 2>&1; then
      note "Updated repo" "$sysdir"
    else
      err "Pull of $sysdir failed"
      note "Failed repo pull" "$sysdir"
    fi
    return
  fi

  if [ "$ahead" -gt 0 ]; then
    log "${GN}Ok${RESET} ($ahead local commit(s) not pushed)"
    return
  fi
  log "${GN}Ok${RESET}"
}

# Capture a repo entry from the system (system -> TT): refresh url/branch
# in the marker. Never captures content, never removes the marker.
# Returns 0 when the marker changed, 1 when unchanged, 2 on error.
function captureRepoFromSystem() {
  local sysdir="$1" gitdir="$2"
  local url branch force
  url=$(readRepoSpec "$gitdir" url)
  branch=$(readRepoSpec "$gitdir" branch)
  force=$(readRepoSpec "$gitdir" force)

  if [ -z "$(ttGitTopLevel "$sysdir")" ]; then
    warn "$sysdir is no longer a git repository root - marker left unchanged"
    note "Skipped repo capture (not a repo)" "$sysdir"
    return 2
  fi

  local new_url new_branch
  new_url=$(git -C "$sysdir" remote get-url origin 2>/dev/null)
  new_branch=$(git -C "$sysdir" rev-parse --abbrev-ref HEAD 2>/dev/null)
  if [ -z "$new_url" ]; then
    warn "$sysdir has no origin remote - marker left unchanged"
    note "Skipped repo capture (no origin)" "$sysdir"
    return 2
  fi
  if [ "$new_branch" = "HEAD" ]; then
    new_branch=""
  fi

  if [ "$new_url" = "$url" ] && [ "$new_branch" = "$branch" ]; then
    return 1
  fi

  # Guard the redirect: if $TTGIT_MARKER is itself a directory (a broken
  # marker isRepoEntry now routes here instead of to mirrorDir), the
  # redirect fails and nothing must be reported as written.
  if {
    echo "url    = $new_url"
    if [ -n "$new_branch" ]; then
      echo "branch = $new_branch"
    fi
    # Case-insensitive, matching the fold in syncRepoToSystem and
    # tui/core/repo.py's spec.force (.lower() == "true").
    if [ "$(printf '%s' "$force" | tr '[:upper:]' '[:lower:]')" = true ]; then
      echo "force  = true"
    fi
  } 2>/dev/null >"$gitdir/$TTGIT_MARKER"; then
    note "Updated repo marker" "$sysdir ($new_url${new_branch:+, branch $new_branch})"
    return 0
  else
    warn "$gitdir/$TTGIT_MARKER could not be written - marker left unchanged"
    note "Skipped repo capture (marker not writable)" "$sysdir"
    return 2
  fi
}

function getInstalledPackages() {
  logn "Preparing list of software for $HOST..."
  for c in common $(<$BASE/configs/$HOST/includes.conf) $HOST; do
    cat $BASE/configs/$c/to_install.$INSTALLER | grep -v "#" >>$1
  done
  sort -u $1 >$1.sorted
  logn "$(wc -l $TMP/to_install.sorted | cut -c1-9) tools to install. "
  log "${GN}done$RESET"
  echo
  log "now: running through all localy installed software"
  logn "Checking: "
  bash -c "$LIST" >$2
}

# --- machine id -------------------------------------------------------
#
# The hostname changes with the network (VPN, DHCP domain, mDNS suffix),
# which used to switch host configs mid-week. $BASE/machine-id pins the
# config name for this machine instead; it need not be a hostname at all.
# The file is machine-local and kept out of the config repo. Parsing must
# match tui/core/machine_id.py: first line, trimmed, empty means unset.

function readMachineId() {
  local f="$BASE/machine-id"
  [ -r "$f" ] || return 0
  head -n1 "$f" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

# The name every config lookup keys on: the pinned id, else the hostname.
function resolveHost() {
  local id
  id=$(readMachineId)
  echo "${id:-$(hostname)}"
}

# Pin $1 as this machine's id. The config dir is a git repo shared by all
# machines, so the id is added to its .gitignore the first time - like
# cache/ - rather than ending up committed from one machine.
function writeMachineId() {
  echo "$1" >"$BASE/machine-id"
  local gi="$BASE/.gitignore"
  if [ -d "$BASE/.git" ] && ! grep -qx 'machine-id' "$gi" 2>/dev/null; then
    {
      echo "# Which host config this machine uses (machine-specific)"
      echo "machine-id"
    } >>"$gi"
  fi
}

# --- reverse-dependency cache (shared with the Python TUI) ------------
#
# $USES is one package-manager call per package and slow enough (~1.3s
# each for brew) that a sync run over a few hundred packages takes
# minutes. The TUI and tt-cleanup-deps cache those answers in
# $BASE/cache/reverse-deps.tsv; this reads the same file so a sync gets
# the same speedup. See tui/core/dep_cache.py for the format.
#
# The cache is only used when its fingerprint matches the currently
# installed package set — otherwise (or if it's missing entirely) every
# lookup falls back to $USES, i.e. exactly the old behaviour. Nothing
# here ever writes the cache; the Python side owns that.

DEP_CACHE_FILE=""

function loadDepCache() {
  DEP_CACHE_FILE=""
  local cache="$BASE/cache/reverse-deps.tsv"
  [ -r "$cache" ] || return 0

  # Must match tui.core.dep_cache.fingerprint(): deduped, bytewise
  # sorted, newline-separated AND newline-terminated.
  local current stored
  current=$(sed '/^$/d' "$TMP/local_installed" | LC_ALL=C sort -u |
    shasum -a 256 2>/dev/null | cut -d' ' -f1)
  stored=$(grep '^# fingerprint ' "$cache" 2>/dev/null | head -1 | cut -d' ' -f3)

  if [ -n "$current" ] && [ "$current" = "$stored" ]; then
    DEP_CACHE_FILE="$cache"
    log "${GN}using cached dependency data$RESET"
  else
    log "${YL}dependency cache stale or missing - falling back to live lookups$RESET"
  fi
}

# Number of installed packages that require $1. Served from the cache
# when it's valid and has an entry for this package, otherwise via $USES.
function depCount() {
  local pkg="$1"
  if [ -n "$DEP_CACHE_FILE" ]; then
    local line
    line=$(grep -F "$(printf '%s\t' "$pkg")" "$DEP_CACHE_FILE" 2>/dev/null |
      awk -F'\t' -v P="$pkg" '$1==P {print $2; exit}')
    # A cached package with no dependents yields an empty field, which is
    # a real answer ("nothing needs it") - distinguish that from "not in
    # the cache at all" by checking for the record, not the value.
    if grep -q -F "$(printf '%s\t' "$pkg")" "$DEP_CACHE_FILE" 2>/dev/null; then
      echo "$line" | wc -w
      return 0
    fi
  fi
  local u
  u=$(echo "$USES" | sed -e "s/%%/$pkg/g")
  bash -c "$u" | wc -w
}

function checkSystem() {

  OS_TYPE="$(uname -s)"
  case "${OS_TYPE}" in

  Darwin*)
    log "$BL Info: Running on macOS$RESET"
    logn "checking brew.sh...."
    brew list >/dev/null || {
      err "brew not installed"
      exit 1
    }
    log "${GN}ok$RESET"
    INSTALLER="brew"
    INSTALL="brew install"
    UNINSTALL="brew uninstall"
    LIST="brew list -1"
    USES="brew uses --installed %%"
    UPDATE="brew update && brew upgrade"
    ;;
  Linux*)
    log "$BL Info: Running on Linux$RESET"
    hash apt && {
      #log "${YL}Attention:${RESET} on linux uninstalling of tools is not supported!"
      INSTALLER="apt"
      INSTALL="sudo apt install -y"
      UNINSTALL="sudo apt purge -y"
      UPDATE="sudo apt-get update && sudo apt-get upgrade -y"
      # apt-cache ships with apt itself (unlike the optional apt-rdepends),
      # so this never silently degrades to "no dependencies" the way the
      # old apt-rdepends-or-nothing check did. --installed restricts the
      # reverse-dependency list to packages that are actually installed
      # right now, matching what syncInstall() needs: "would removing $l
      # break something on THIS system", not "could it in theory".
      # --important limits it to Depends/Pre-Depends, excluding Recommends/
      # Suggests/Conflicts/Breaks/Replaces/Enhances — without it, common
      # Recommends relationships would make this keep packages that would
      # actually be fine to remove.
      USES="apt-cache rdepends --installed --important %% 2>/dev/null | awk '/Reverse Depends:/{f=1;next} f && NF'"
      LIST="apt list --installed | grep -v Listing... |/usr/bin/cut -f1 -d/"

    }
    hash pacman && {
      log "${YL}Attention:${RESET} on linux uninstalling of tools is not supported!"
      INSTALLER="pacman"
      INSTALL="sudo pacman -Sy --noconfirm"
      UPDATE="sudo pacman -Syu --noconfirm"
      # Emit the actual dependent names (like the apt/brew branches above),
      # not a pre-counted number — bin/tt's syncInstall() pipes $USES's
      # output through `wc -w` itself. The old "...| wc -l" here produced
      # a single-line number, and counting the WORDS of that number with
      # wc -w always came out to 1 regardless of whether it was "0" or
      # "7" — so every pacman package looked like a dependency and was
      # never actually removed (masked, harmlessly, by UNINSTALL being
      # unset for pacman below — see the guard in syncInstall()).
      USES='pacman -Qi %% | sed -n "s/^Required By *: //p" | grep -vx None | tr " " "\n" | grep -v "^$"'
      LIST="pacman -Q | awk '{print \$1}'"
    }
    if [ -z $INSTALLER ]; then
      err "no valid package manager found, apt and pacman are supported"
      exit 1
    fi

    ;;
  *)
    echo -e "$ERR Unknown Operating System:$RESET$OS_TYPE"
    exit 1
    ;;
  esac
}

function menu() {
  local prompt="$1"
  shift
  local options=("$@")

  if fzf_available; then
    local numbered=()
    local idx=1
    for opt in "${options[@]}"; do
      numbered+=("$(printf "%2d. %b" "$idx" "$opt")")
      ((idx = idx + 1))
    done
    local selection
    if selection=$(printf "%s\n" "${numbered[@]}" | fzf_themed \
        --no-sort --no-multi --tac \
        --border-label=" $prompt " \
        --info=hidden \
        --height="~$((${#options[@]} + 4))" \
        --prompt="> "); then
      local num
      num=$(echo "$selection" | sed 's/^ *//' | cut -d. -f1)
      echo "${num}:${options[$((num - 1))]}"
      return 0
    fi
    return 1
  fi

  log "$prompt" >/dev/tty
  local idx=1
  for opt in "${options[@]}"; do
    printf "%b%2d.%b %b\n" "$YL" "$idx" "$RESET" "$opt" >/dev/tty
    ((idx = idx + 1))
  done

  while true; do
    echo -n "${PS3:-Choose option -> }" >/dev/tty
    read -r key </dev/tty || return 1
    if [[ "$key" =~ ^[0-9]+$ ]] && [ "$key" -ge 1 ] && [ "$key" -le "${#options[@]}" ]; then
      echo "$key:${options[$((key - 1))]}"
      return 0
    fi
    warn "Enter a number between 1 and ${#options[@]}"
  done
}
