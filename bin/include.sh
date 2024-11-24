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
    ;;
  Linux*)
    log "$BL Info: Running on Linux$RESET"
    hash apt && {
      #log "${YL}Attention:${RESET} on linux uninstalling of tools is not supported!"
      INSTALLER="apt"
      INSTALL="sudo apt install -y"
      UNINSTALL="sudo apt purge -y"
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
      INSTALL="sudo pacman -Sy"
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
  log "$1" >/dev/tty
  shift
  a=("$@")
  n=1
  while true; do
    for i in "$@"; do
      echo -e "${YL}$n$RESET. $i$RESET" >/dev/tty
      ((n = n + 1))
    done
    n=1
    echo -n "$PS3" >/dev/tty
    read key </dev/tty >/dev/null
    idx=$((key - 1))
    echo -n "$key:${a[$idx]}"
    return
  done
}
