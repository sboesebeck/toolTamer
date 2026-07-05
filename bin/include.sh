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

# Mirror directory $1 into $2: full copy including deletion of files that
# are not present in the source. Uses rsync when available.
function mirrorDir() {
  local src="$1"
  local dst="$2"
  mkdir -p "$dst" || return 1
  if command -v rsync >/dev/null 2>&1; then
    if rsync -a --delete "$src/" "$dst/"; then
      return 0
    fi
    warn "rsync failed - falling back to manual mirror"
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
  done < <(listDirExtras "$gitdir" "$sysdir")
  mkdir -p "$(dirname "$sysdir")"
  mirrorDir "$gitdir" "$sysdir" || err "Directory sync failed for $sysdir"
}

# Capture a system directory into the TT store (system -> TT).
# Performs a full mirror: files removed on the system are removed in TT too.
function captureDirFromSystem() {
  local sysdir="$1"
  local gitdir="$2"
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
      if hash apt-rdepends; then
        USES="apt-rdepends -r %% 2>/dev/null | grep Reverse"
      else
        log "${YL}Warning:$RESET cannot determine dependencies, consider installing apt-rdepends."
        USES="echo 'no dependencies'"
      fi
      LIST="apt list --installed | grep -v Listing... |/usr/bin/cut -f1 -d/"

    }
    hash pacman && {
      log "${YL}Attention:${RESET} on linux uninstalling of tools is not supported!"
      INSTALLER="pacman"
      INSTALL="sudo pacman -Sy --noconfirm"
      UPDATE="sudo pacman -Syu --noconfirm"
      USES='pacman -Qi %% | grep "Required By " | grep -v None |tr " " "\n"| wc -l'
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
