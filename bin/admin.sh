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

    for i in $(<$l/includes.conf) common; do
      for p in $(<$BASE/configs/$i/to_install.$pkg); do
        if grep "^$p\$" $l/to_install.$pkg; then
          log "Found duplicate Entry $p - included from $i - ${RD}removing it$RESET"
          read
          grep -v "^$p\$" $l/to_install.$pkg >$TMP/to_install.tmp && mv $TMP/to_install.tmp $l/to_install.$pkg
        fi
      done
    done
  done
  log "${GN}Checks done$RESET"

}

function addPackage() {
  log "Enter package you want to add to local config?"
  read p
  if [ -z "$p" ]; then
    echo "abort"
    return
  fi
  log "Installing $p...."
  $INSTALL $p >/dev/null || exit 1
  echo $p >>$BASE/configs/$HOST/to_install.$INSTALLER
  log "added ${BL}$p$RESET to local installation"
}

function movePackage() {
  localConfig=$BASE/configs/$HOST/to_install.$INSTALLER
  log "Move a ${BL}local$RESET package to an other config"
  pkgs=$(cat $BASE/configs/$HOST/to_install.$INSTALLER | fzf)
  cd $BASE/configs
  dest=$(ls -1 | fzf)
  echo "you chose $(echo "$pkgs" | wc -w) packages to move to $dest"
  for p in $pkgs; do
    log "Moving $BL$p$RESET."
    if [ ! -e $BASE/configs/$dest/to_install.$INSTALLER ]; then
      err "$dest not found"
      continue
    fi
    destConfig=$BASE/configs/$dest/to_install.$INSTALLER
    grep -v "$p" $localConfig >${localConfig}.tmp
    l1=$(wc -l <${localConfig}.tmp)
    l2=$(wc -l <${localConfig})
    ((d = $l2 - $l1))
    if [ $d -ne 1 ]; then
      err "Somethign is wrong - too many ($BL$d$RESET) packages removed for $p - ${RD}Aborting$RESET"
      rm -f ${localConfig}.tmp
    fi
    mv ${localConfig}.tmp $localConfig
    echo "$p" >>$destConfig
  done
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

function show_file_diff_viewer() {
  local repo="$1"
  local target="$2"
  if command -v difft >/dev/null 2>&1; then
    difft "$repo" "$target"
  else
    diff -u "$repo" "$target" | less -R
  fi
}

function pause_admin() {
  if [ -t 1 ]; then
    echo
    log "${CN}Press enter to return to the list...$RESET"
    read -r </dev/tty
    echo
  fi
}

function array_contains_value() {
  local needle="$1"
  shift
  for item in "$@"; do
    if [ "$item" = "$needle" ]; then
      return 0
    fi
  done
  return 1
}

function sanitize_rel_path() {
  local rel="$1"
  rel="${rel#/}"
  echo "$rel" | sed -e 's!/!/_/g'
}

function list_available_configs() {
  local choices=()
  if [ -n "$HOST" ]; then
    choices+=("$HOST")
  fi
  if [ -f "$BASE/configs/$HOST/includes.conf" ]; then
    while IFS= read -r inc; do
      [ -z "$inc" ] && continue
      array_contains_value "$inc" "${choices[@]}" || choices+=("$inc")
    done <"$BASE/configs/$HOST/includes.conf"
  fi
  array_contains_value "common" "${choices[@]}" || choices+=("common")
  while IFS= read -r cfg; do
    [ -z "$cfg" ] && continue
    array_contains_value "$cfg" "${choices[@]}" || choices+=("$cfg")
  done < <(ls -1 "$BASE/configs")
  printf "%s\n" "${choices[@]}"
}

function ensure_file_mapping_entry() {
  local config="$1"
  local stored="$2"
  local rel="$3"
  local conf_file="$BASE/configs/$config/files.conf"
  touch "$conf_file"
  if ! grep -Fq ";$rel" "$conf_file" 2>/dev/null; then
    echo "$stored;$rel" >>"$conf_file"
  fi
}

function report_existing_entries_for_file() {
  local rel="$1"
  local have_entries=0
  while IFS= read -r cfg; do
    [ -z "$cfg" ] && continue
    local conf_file="$BASE/configs/$cfg/files.conf"
    [ -f "$conf_file" ] || continue
    while IFS=';' read -r stored dest; do
      [ -z "$stored" ] && continue
      [[ "$stored" =~ ^# ]] && continue
      if [ "$dest" = "$rel" ]; then
        have_entries=1
        local repo_file="$BASE/configs/$cfg/files/$stored"
        if [ -f "$repo_file" ]; then
          local repo_hash
          local sys_hash
          repo_hash=$(shasum <"$repo_file")
          sys_hash=$(shasum <"$HOME/$rel")
          if [ "$repo_hash" = "$sys_hash" ]; then
            log "${GN}File already matches$RESET in config ${BL}$cfg$RESET (${repo_file##$BASE/configs/})"
          else
            log "${YL}Difference detected$RESET with config ${BL}$cfg$RESET (${repo_file##$BASE/configs/})"
            show_file_diff_viewer "$repo_file" "$HOME/$rel"
            pause_admin
          fi
        else
          warn "Entry for $rel found in $cfg, but file $repo_file is missing"
        fi
        break
      fi
    done <"$conf_file"
  done < <(ls -1 "$BASE/configs")
  return $have_entries
}

function add_local_file_to_tooltamer() {
  local original_dir
  original_dir=$(pwd)
  cd "$HOME" || return
  local selection
  selection=$(fzf --border-label="Choose file to add" --preview='[ -f {} ] && command tail -n +1 {} | head -n 200' --height=80%) || {
    log "Abort"
    cd "$original_dir" || true
    return
  }
  if [ -z "$selection" ]; then
    log "Abort"
    cd "$original_dir" || true
    return
  fi
  if [ -d "$selection" ]; then
    err "Directory selection is not supported yet."
    cd "$original_dir" || true
    return
  fi
  local abs="$HOME/$selection"
  if [ ! -f "$abs" ]; then
    err "File $abs not found"
    cd "$original_dir" || true
    return
  fi

  report_existing_entries_for_file "$selection"

  mapfile -t config_choices < <(list_available_configs)
  local dest_config
  dest_config=$(printf "%s\n" "${config_choices[@]}" | fzf --prompt="config> " --header="Select destination config for $selection") || {
    log "Abort"
    cd "$original_dir" || true
    return
  }
  if [ -z "$dest_config" ]; then
    log "Abort"
    cd "$original_dir" || true
    return
  fi

  local stored_name
  stored_name=$(sanitize_rel_path "$selection")
  local dest_dir="$BASE/configs/$dest_config/files"
  mkdir -p "$dest_dir"
  local repo_file="$dest_dir/$stored_name"

  if [ -f "$repo_file" ]; then
    local action
    action=$(menu "File already exists in ${dest_config}. Replace with local version?" "Replace version in ToolTamer" "Keep current ToolTamer version" "View diff and decide later") || {
      cd "$original_dir" || true
      return
    }
    case "${action%%:*}" in
    "1")
      cp "$abs" "$repo_file"
      ;;
    "2")
      log "Keeping existing ToolTamer version for $selection"
      cd "$original_dir" || true
      return
      ;;
    "3")
      show_file_diff_viewer "$repo_file" "$abs"
      pause_admin
      cd "$original_dir" || true
      return
      ;;
    esac
  else
    cp "$abs" "$repo_file"
  fi

  ensure_file_mapping_entry "$dest_config" "$stored_name" "$selection"
  log "${GN}Added${RESET} ${BL}$selection$RESET to config ${CN}$dest_config$RESET"
  pause_admin
  cd "$original_dir" || true
}

function reviewManagedFileDiffs() {
  createEffectiveFilesList $TMP/files.lst
  while true; do
    local entries=()
    local lines=()
    local idx=0
    while IFS= read -r entry; do
      [ -z "$entry" ] && continue
      local repo="${entry%%;*}"
      local target="${entry##*;}"
      if [ -z "$repo" ] || [ -z "$target" ]; then
        continue
      fi
      if [ ! -e "$repo" ] || [ ! -e "$target" ]; then
        continue
      fi
      local repo_hash
      local target_hash
      repo_hash=$(shasum <"$repo")
      target_hash=$(shasum <"$target")
      if [ "$repo_hash" = "$target_hash" ]; then
        continue
      fi
      entries[idx]="$repo;$target"
      local target_disp="${target#$HOME/}"
      if [ "$target_disp" = "$target" ]; then
        target_disp="$target"
      else
        target_disp="~/$target_disp"
      fi
      local repo_disp="${repo##$BASE/configs/}"
      lines[idx]="${idx}\t${BL}${target_disp}${RESET} ${MG}<->${RESET} ${repo_disp}"
      ((idx = idx + 1))
    done < $TMP/files.lst

    if [ "${#entries[@]}" -eq 0 ]; then
      log "${GN}All tracked files are in sync$RESET"
      return
    fi

    local selection
    selection=$(printf "%b\n" "${lines[@]}" | fzf --ansi --with-nth=2.. --prompt="diff> " --header="Select a file to inspect (ESC to exit)") || return
    local sel_idx=${selection%%$'\t'*}
    if [ -z "$sel_idx" ]; then
      return
    fi
    local meta="${entries[$sel_idx]}"
    local repo="${meta%%;*}"
    local target="${meta##*;}"
    show_file_diff_viewer "$repo" "$target"
    pause_admin
    local action
    if ! action=$(menu "Apply change for ${target#$HOME/}?" "Add to ToolTamer" "Revert local change" "Ignore"); then
      continue
    fi
    case "${action%%:*}" in
    "1")
      cp "$target" "$repo"
      log "${GN}Copied$RESET $target -> $repo"
      ;;
    "2")
      cp "$repo" "$target"
      log "${YL}Reverted$RESET $target from ToolTamer"
      ;;
    *)
      log "Ignoring change for $target"
      ;;
    esac
  done
}

TMP=/tmp/tt$$
if [ ! -e $TMP ]; then
  mkdir $TMP
fi
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
  if ! o=$(menu "---> ToolTamer Admin Menu <---" "Move ${BL}l${RESET}ocal file to ${BL}ToolTamer$RESET" "Move files between configs in ${BL}ToolTamer$RESET" "View ${BL}d${RESET}ifferences of files" "View differences of ${BL}i${RESET}nstalled tools" "Show ${BL}C${RESET}onfig" "${BL}F${RESET}ix duplicate packages" "${BL}G${RESET}it view" "Add ${BL}P${RESET}ackage to installation" "M${BL}o${RESET}ve installed package" "${YL}return$RESET (${BL}q${RESET}/${BL}r$RESET)"); then
    log "Leaving admin menu."
    break
  fi
  if [ -z "$o" ]; then
    log "Leaving admin menu."
    break
  fi
  log "Option: $o"
  n=${o%%:*}
  o=${o##*:}
  log "Got option ${YL}$o$RESET (number $n)"
  case "$n" in
  "1" | "L" | "l")
    add_local_file_to_tooltamer
    ;;
  "2" | "m")
    cd $BASE/configs
    ls -1 | fzf
    ;;
  "3" | "d" | "D")
    reviewManagedFileDiffs
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
    while true; do
      o=$(menu "Do you want to install missing packages?" "Yes" "No")
      n=${o%%:*}
      o=${o##*:}

      case "$n" in
      "1" | "y" | "Yes" | "Y")
        err "not implemented yet - sorry"
        break
        ;;
      "2" | "n" | "No" | "N")
        break
        ;;
      *)
        log "Hä?"
        ;;
      esac
    done
    while true; do
      o=$(menu "Do you want to remove installed packages?" "Yes" "No")
      n=${o%%:*}
      o=${o##*:}

      case "$n" in
      "1" | "y" | "Yes" | "Y")
        lst=$(printf "%s\n" "$toRemove" | fzf -m)
        if [ $? -ne 0 ] || [ -z "$lst" ]; then
          log "${YL}No packages selected$RESET - skipping removal"
        else
          log "${YL}Removing$RESET: $lst"
          $UNINSTALL $lst
        fi
        break
        ;;
      "2" | "n" | "No" | "N")
        break
        ;;
      *)
        log "Hä?"
        ;;
      esac
    done
    while true; do
      o=$(menu "Do you want to Add installed packages to ToolTamer?" "Yes" "No")
      n=${o%%:*}
      o=${o##*:}

      case "$n" in
      "1" | "y" | "Yes" | "Y")
        lst=$(printf "%s\n" "$toRemove" | fzf -m)
        if [ $? -ne 0 ] || [ -z "$lst" ]; then
          log "${YL}No packages selected$RESET - not adding anything."
        else
          log "${YL}adding$RESET: $lst"
          for i in $lst; do
            echo "$i" >>$BASE/configs/$HOST/to_install.$INSTALLER
          done
        fi
        break
        ;;
      "2" | "n" | "No" | "N")
        break
        ;;
      *)
        log "Hä?"
        ;;
      esac
    done
    log "\n${GN}done.$RESET"
    pause_admin
    ;;
  "5" | "c" | "C")
    showConfig
    pause_admin
    ;;
  "6" | "F" | "f")
    fixDuplicates
    pause_admin
    ;;
  "7" | "g" | "G")
    {
      cd $BASE/
      lazygit
    }
    pause_admin
    ;;
  "8" | "p")
    addPackage
    pause_admin
    ;;
  "9" | "o")
    movePackage
    pause_admin
    ;;
  "10" | "q" | "Q" | "r")
    return
    ;;
  esac
done
