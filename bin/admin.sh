if [ ! -e $BASE ]; then
  err "no config dir found - plase call $(dirname $0)/tt to create a default"
  exit 1
fi

function fixDuplicates() {

  rm -f $TMP/install_check
  cd $BASE/configs
  l=$(ls | fzf)

  if [ -z "$l" ]; then
    return
  fi

  for pkg in "brew" "apt"; do
    if [ ! -e $l/to_install.$pkg ]; then
      continue
    fi

    for i in $(<$l/to_install.$pkg); do
      log "Package $i"
      echo "$i" >>$TMP/install_check
    done

    for i in $(<$l/includes.conf) common; do
      for p in $(<$BASE/configs/$i/to_install.$pkg); do
        if grep "^$p\$" $TMP/install_check; then
          log "Found duplicate Entry $p - included from $i - ${RD}removing it$RESET"
          read
          grep -v "^$p\$" $BASE/configs/$i/to_install.$pkg >$TMP/to_install.tmp && mv $TMP/to_install.tmp $BASE/configs/$i/to_install.$pkg
        else
          echo "$p" >>$TMP/install_check
        fi
      done
    done
  done
  log "${GN}Checks done$RESET"

}

function showConfig() {
  rm -f $TMP/install_check
  cd $BASE/configs
  l=$(ls | fzf)
  if [ -z "$l" ]; then
    return
  fi
  for pkg in "brew" "apt"; do
    if [ ! -e $l/to_install.$pkg ]; then
      continue
    fi
    log "---> SoftwareList $pkg: <--- "

    for i in $(<$l/to_install.$pkg); do
      log "Package $i"
      echo "$i" >>$TMP/install_check
    done

    for i in $(<$l/includes.conf) common; do
      log "---> Included from $i:"
      for p in $(<$BASE/configs/$i/to_install.$pkg); do
        if grep "^$p\$" $TMP/install_check; then
          log "  DUPLICATE from $i -> $p"
        else
          log "  Package from $i -> $p"
          echo "$p" >>$TMP/install_check
        fi
      done
    done
  done | fzf --reverse
}

TMP=/tmp/tt$$
mkdir $TMP
touch $TMP/log
cd $BASE || exit 1

HOST=$(hostname)
if [ ! -e $BASE/configs/$HOST ]; then
  err "No config for $HOST - start tt"
  exit 0
fi

log "----> ${BL}Tool${YL}Tamer$RESET V1.0 <----"

if ! hash fzf; then
  err "FZF needs to be installed"
  exit 1
fi
PS3="Choose an option-> "

while true; do
  o=$(menu "---> ToolTamer Admin Menu <---" "Move ${BL}l${RESET}ocal file to ${BL}ToolTamer$RESET" "Move files between configs in ${BL}ToolTamer$RESET" "View ${BL}d${RESET}ifferences of files" "View differences of ${BL}i${RESET}nstalled tools" "Show ${BL}C${RESET}onfig" "${BL}F${RESET}ix duplicate packages" "${YL}return$RESET")
  log "Option: $o"
  n=${o%%:*}
  o=${o##*:}
  log "Got option ${YL}$o$RESET (number $n)"
  case "$n" in
  "1" | "L" | "l")
    cd $HOME
    f=$(fzf -m --border-label="chose file to move to config" --border=rounded)
    if [ -z $f ]; then
      log "Abort"
    else
      warn "Copying $f to local config for $HOST - ok? (enter/CTRL-C)"
      read
      lf=${f#$HOME}
      lf=${lf#/}
      lf=${lf#.}
      if [ -e $BASE/configs/$HOST/files/$lf ]; then
        prflf=$(shasum <$BASE/configs/$HOST/files/$lf)
        prf=$(shasum <$f)
        if [ "$prflf" != "$prf" ]; then
          log "Checksum differs - copying"
          cp $f $BASE/configs/$HOST/files/$lf
        else
          log "File is identical - not copying"
        fi
        if grep $lf $BASE/configs/$HOST/files.conf >/dev/null 2>&1; then
          log "File is in config"
        else
          err "File not in file.conf - ${GN}adding it$RESET"
          echo "$lf;$f" >>$BASE/configs/$HOST/files.conf
        fi
      else
        log "New file - ${GN}adding$RESET"
        cp $HOME/$f $BASE/configs/$HOST/files/$lf || exit 1
        echo "$lf;$f" >>$BASE/configs/$HOST/files.conf
      fi
      log "${GN}done$RESET"
    fi
    ;;
  "2" | "m")
    cd $BASE/configs
    ls -1 | fzf
    ;;
  "3" | "d" | "D")
    createEffectiveFilesList $TMP/files.lst
    cat $TMP/files.lst | while read i; do
      f=$(echo "$i" | cut -f1 -d\;)
      d=$(echo "$i" | cut -f2 -d\;)
      f_sha=$(shasum <"$f")
      d_sha=$(shasum <"$d")
      if [ "$f_sha" = "$d_sha" ]; then
        log "----> file $d... ${GN}ok${RESET}"
      else
        log "----> file $d... ${RD}differs$RESET"
        q=$(menu "Do you want to see diff?" "Yes" "No")
        o=${q%%:*}
        l=${q#*:}
        case "$o" in
        "1")
          difft $f $d
          q=$(menu "Add change to ToolTamer or revert the change?" "Add to ToolTamer" "Revert local change" "Ignore")
          o=${q%%:*}
          l=${q#*:}
          case "$o" in
          "1")
            cp "$d" "$f"
            log "File ${BL}$d$RESET was copied to ToolTamer!"
            ;;
          "2")
            cp "$f" "$d"
            log "File ${BL}$d$RESET was ${YL}replaced$RESET with ToolTamer version!"
            ;;
          "3")
            log "ingoring..."
            ;;
          esac

          ;;
        *) ;;
        esac
      fi
    done

    ;;
  "4" | "i" | "I")
    checkSystem
    echo "Checking installed packages using $INSTALLER..."
    getInstalledPackages $TMP/to_install $TMP/installed
    toInstall=""
    toRemove=""
    touch $TMP/missing
    touch $TMP/exceed
    cat $TMP/to_install | while read l; do
      if ! grep $l $TMP/installed >/dev/null; then
        echo "$l" >>$TMP/missing
      fi
    done
    toInstall=$(sort -u $TMP/missing)
    cat $TMP/installed | while read l; do
      if ! grep $l $TMP/to_install >/dev/null; then
        toRemove="$toRemove $l"
        echo "$l" >>$TMP/exceed
      fi
    done
    toRemove=$(sort -u $TMP/exceed)
    if [ -z "$toInstall" ] && [ -z "$toRemove" ]; then
      log "${GN}All in sync$RESET no differences found"
    else
      log "Differences in installation:"
      if [ ! -z "$toInstall" ]; then
        log "Packages that should be installed:\n$toInstall"
      fi
      if [ ! -z "$toRemove" ]; then
        log "Packages that will be removed:\n$toRemove"
      fi
    fi
    log "\n${GN}done.$RESET"
    ;;
  "5" | "c" | "C")
    showConfig
    ;;
  "6" | "F" | "f")
    fixDuplicates
    ;;
  "7" | "q" | "Q" | "r")
    return
    ;;
  esac
done
