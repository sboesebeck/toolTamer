if [ ! -e $BASE ]; then
  err "no config dir found - plase call $(dirname $0)/tt to create a default"
  exit 1
fi

function fixDuplicates() {

  cd $BASE/configs || return
  local config
  config=$(ls | fzf --prompt="Select config for duplicate cleanup> ")

  if [ -z "$config" ]; then
    return
  fi

  local report="$TMP/${config}_duplicate_report"
  >"$report"

  for pkg in "brew" "apt" "pacman"; do
    find_package_duplicates_for_config "$config" "$pkg" "$report"
  done

  if [ ! -s "$report" ]; then
    log "${GN}No duplicate packages found$RESET for ${BL}$config$RESET"
    return
  fi

  log "Duplicate packages detected for ${BL}$config$RESET:"
  local display="$TMP/${config}_dup_display"
  >"$display"
  while IFS=';' read -r pkgtype pkg reason; do
    case "$reason" in
    parent:*)
      local parent=${reason#parent:}
      log "  [$pkgtype] ${BL}$pkg$RESET already exists in ${CN}$parent$RESET"
      echo "$pkgtype;$pkg;$reason;[$pkgtype] $pkg (in parent $parent)" >>"$display"
      ;;
    local)
      log "  [$pkgtype] ${BL}$pkg$RESET is listed multiple times in ${CN}$config$RESET"
      echo "$pkgtype;$pkg;$reason;[$pkgtype] $pkg (duplicated locally)" >>"$display"
      ;;
    esac
  done <"$report"

  local chosen_lines=()
  if ! mapfile -t chosen_lines < <(cat "$display" | fzf --ansi --multi --with-nth=4 --prompt="remove> " --header="Select duplicates to remove from ${config} (TAB to toggle, CTRL-A for all, ESC to cancel)"); then
    log "No packages selected for removal."
    pause_admin
    return
  fi
  if [ "${#chosen_lines[@]}" -eq 0 ]; then
    log "No packages selected for removal."
    pause_admin
    return
  fi

  rm -f $TMP/${config}_*_selected_parent $TMP/${config}_*_selected_local 2>/dev/null
  for line in "${chosen_lines[@]}"; do
    IFS=';' read -r pkgtype pkg reason desc <<<"$line"
    [ -z "$pkgtype" ] && continue
    case "$reason" in
    parent:*)
      echo "$pkg" >>"$TMP/${config}_${pkgtype}_selected_parent"
      ;;
    local)
      echo "$pkg" >>"$TMP/${config}_${pkgtype}_selected_local"
      ;;
    esac
  done

  apply_package_duplicate_cleanup "$config"
  log "${GN}Duplicate cleanup complete.$RESET"
  pause_admin
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

function trim_string() {
  local str="$1"
  str="${str#"${str%%[![:space:]]*}"}"
  str="${str%"${str##*[![:space:]]}"}"
  echo "$str"
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

function remove_file_mapping_entry() {
  local config="$1"
  local stored="$2"
  local rel="$3"
  local conf_file="$BASE/configs/$config/files.conf"
  [ -f "$conf_file" ] || return
  awk -F';' -v s="$stored" -v t="$rel" '
  function trim(str) {
    gsub(/^[ \t]+|[ \t]+$/, "", str)
    return str
  }
  {
    orig=$0
    if (trim($1) == s && trim($2) == t) {
      next
    }
    print orig
  }
  ' "$conf_file" >"$conf_file.tmp" && mv "$conf_file.tmp" "$conf_file"
}

function collect_config_file_entries() {
  local config="$1"
  local output="$2"
  local conf_file="$BASE/configs/$config/files.conf"
  : >"$output"
  [ -f "$conf_file" ] || return 1
  while IFS= read -r line; do
    line=$(echo "$line" | sed 's/\r$//')
    if [ -z "$line" ] || [[ "$line" =~ ^# ]]; then
      continue
    fi
    local stored="${line%%;*}"
    local dest="${line#*;}"
    stored=$(trim_string "$stored")
    dest=$(trim_string "$dest")
    if [ -z "$stored" ] || [ -z "$dest" ]; then
      continue
    fi
    echo "$stored;$dest" >>"$output"
  done <"$conf_file"
}

function find_stored_for_target() {
  local config="$1"
  local rel="$2"
  local conf_file="$BASE/configs/$config/files.conf"
  [ -f "$conf_file" ] || return
  awk -F';' -v t="$rel" '
  function trim(str) {
    gsub(/^[ \t]+|[ \t]+$/, "", str)
    return str
  }
  {
    if (trim($2) == t) {
      print trim($1)
      exit
    }
  }
  ' "$conf_file"
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

function list_parent_configs_for() {
  local cfg="$1"
  local parents=()
  if [ "$cfg" = "common" ]; then
    return
  fi
  parents+=("common")
  if [ -f "$BASE/configs/$cfg/includes.conf" ]; then
    while IFS= read -r inc; do
      inc=$(echo "$inc" | sed -e 's/#.*//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
      [ -z "$inc" ] && continue
      array_contains_value "$inc" "${parents[@]}" || parents+=("$inc")
    done <"$BASE/configs/$cfg/includes.conf"
  fi
  printf "%s\n" "${parents[@]}"
}

function list_child_configs_for() {
  local needle="$1"
  while IFS= read -r cfg; do
    [ -z "$cfg" ] && continue
    [ "$cfg" = "$needle" ] && continue
    local inc_file="$BASE/configs/$cfg/includes.conf"
    [ -f "$inc_file" ] || continue
    if grep -Fxq "$needle" "$inc_file"; then
      echo "$cfg"
    fi
  done < <(ls -1 "$BASE/configs")
}

function normalize_pkg_line() {
  echo "$1" | sed -e 's/#.*//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

function build_parent_package_map() {
  local cfg="$1"
  local pkgtype="$2"
  local output="$3"
  : >"$output"
  while IFS= read -r parent; do
    [ -z "$parent" ] && continue
    local parent_file="$BASE/configs/$parent/to_install.$pkgtype"
    [ -f "$parent_file" ] || continue
    while IFS= read -r line; do
      local pkg=$(normalize_pkg_line "$line")
      [ -z "$pkg" ] && continue
      echo "$pkg;$parent" >>"$output"
    done <"$parent_file"
  done < <(list_parent_configs_for "$cfg")
  if [ -s "$output" ]; then
    sort -u "$output" -o "$output"
  fi
}

function find_package_duplicates_for_config() {
  local cfg="$1"
  local pkgtype="$2"
  local report="$3"
  local config_file="$BASE/configs/$cfg/to_install.$pkgtype"
  [ -f "$config_file" ] || return

  local parent_map="$TMP/${cfg}_${pkgtype}_parent_map"
  local parent_dup="$TMP/${cfg}_${pkgtype}_parent_found"
  local local_dup="$TMP/${cfg}_${pkgtype}_local_found"
  local seen_file="$TMP/${cfg}_${pkgtype}_seen"
  : >"$parent_dup"
  : >"$local_dup"
  : >"$seen_file"

  build_parent_package_map "$cfg" "$pkgtype" "$parent_map"

  while IFS= read -r line; do
    local pkg=$(normalize_pkg_line "$line")
    [ -z "$pkg" ] && continue
    if [ -s "$parent_map" ] && grep -Fq "^$pkg;" "$parent_map"; then
      local parent=$(grep -F "^$pkg;" "$parent_map" | head -n1)
      parent=${parent#*;}
      if ! grep -Fxq "$pkg" "$parent_dup"; then
        echo "$pkg" >>"$parent_dup"
        echo "$pkgtype;$pkg;parent:$parent" >>"$report"
      fi
      continue
    fi
    if grep -Fxq "$pkg" "$seen_file"; then
      if ! grep -Fxq "$pkg" "$local_dup"; then
        echo "$pkg" >>"$local_dup"
        echo "$pkgtype;$pkg;local" >>"$report"
      fi
      continue
    fi
    echo "$pkg" >>"$seen_file"
  done <"$config_file"

  rm -f "$seen_file" "$parent_map" "$parent_dup" "$local_dup"
}

function deduplicate_package_file() {
  local file="$1"
  local list_file="$2"
  local tmp="$file.tmp"
  local targets=""
  if [ -n "$list_file" ] && [ -f "$list_file" ]; then
    targets=$(tr '\n' ' ' <"$list_file")
  fi
  awk -v targets="$targets" '
  function trim(str) {
    sub(/^[ \t]+/, "", str)
    sub(/[ \t]+$/, "", str)
    return str
  }
  BEGIN {
    if (targets != "") {
      split(targets, arr, " ")
      for (i in arr) {
        if (arr[i] != "")
          wanted[arr[i]] = 1
      }
    }
  }
  {
    orig=$0
    trimmed=trim(orig)
    if (trimmed == "" || trimmed ~ /^#/) {
      print orig
      next
    }
    if (targets == "") {
      if (!seen_all[trimmed]++) {
        print orig
      }
      next
    }
    if (!wanted[trimmed]) {
      print orig
      next
    }
    seen_partial[trimmed]++
    if (seen_partial[trimmed] == 1) {
      print orig
    }
  }
  ' "$file" >"$tmp"
  mv "$tmp" "$file"
}

function apply_package_duplicate_cleanup() {
  local cfg="$1"
  local managers=("brew" "apt" "pacman")
  for pkgtype in "${managers[@]}"; do
    local config_file="$BASE/configs/$cfg/to_install.$pkgtype"
    [ -f "$config_file" ] || continue
    local parent_dup="$TMP/${cfg}_${pkgtype}_selected_parent"
    local local_dup="$TMP/${cfg}_${pkgtype}_selected_local"
    if [ -f "$parent_dup" ]; then
      local tmp="$config_file.tmp"
      cp "$config_file" "$tmp"
      while IFS= read -r pkg; do
        [ -z "$pkg" ] && continue
        grep -v -x "$pkg" "$tmp" >"$tmp.filtered" && mv "$tmp.filtered" "$tmp"
      done <"$parent_dup"
      mv "$tmp" "$config_file"
      rm -f "$parent_dup"
      log "  Removed parent duplicates from ${BL}$cfg$RESET [$pkgtype]"
    fi
    if [ -f "$local_dup" ]; then
      deduplicate_package_file "$config_file" "$local_dup"
      rm -f "$local_dup"
      log "  Removed repeated entries inside ${BL}$cfg$RESET [$pkgtype]"
    fi
    rm -f "$TMP/${cfg}_${pkgtype}_parent_map"
  done
}

function add_local_file_to_tooltamer() {
  local original_dir
  original_dir=$(pwd)
  cd "$HOME" || return
  local selection
  selection=$(fzf --border-label="Choose file to add" --preview='[ -f {} ] && sed -n "1,200p" "{}"' --height=80%) || {
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

  local config_choices=()
  while IFS= read -r cfg; do
    [ -z "$cfg" ] && continue
    config_choices+=("$cfg")
  done < <(list_available_configs)
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

function select_destination_config() {
  local source="$1"
  local parents=()
  local children=()
  if [ -n "$source" ]; then
    mapfile -t parents < <(list_parent_configs_for "$source")
    mapfile -t children < <(list_child_configs_for "$source")
  fi
  local options=()
  while IFS= read -r cfg; do
    [ -z "$cfg" ] && continue
    [ "$cfg" = "$source" ] && continue
    local tag="[config]"
    if array_contains_value "$cfg" "${parents[@]}"; then
      tag="[parent]"
    elif array_contains_value "$cfg" "${children[@]}"; then
      tag="[child]"
    elif [ "$cfg" = "common" ]; then
      tag="[common]"
    elif [ "$cfg" = "$HOST" ]; then
      tag="[host]"
    fi
    local label="$tag $cfg"
    if array_contains_value "$cfg" "${parents[@]}"; then
      label="$label (parent)"
    elif array_contains_value "$cfg" "${children[@]}"; then
      label="$label (child)"
    fi
    options+=("$cfg"$'\t'"$label")
  done < <(ls -1 "$BASE/configs")
  if [ "${#options[@]}" -eq 0 ]; then
    echo ""
    return
  fi
  local selection
  selection=$(printf "%s\n" "${options[@]}" | fzf --with-nth=2.. --prompt="destination> " --header="Select destination config") || {
    echo ""
    return
  }
  echo "${selection%%$'\t'*}"
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

function move_files_between_configs() {
  local source
  source=$(ls -1 "$BASE/configs" | fzf --prompt="source config> " --header="Choose config to move/copy files from")
  if [ -z "$source" ]; then
    log "Abort"
    pause_admin
    return
  fi

  local entries_file="$TMP/${source}_file_entries"
  if ! collect_config_file_entries "$source" "$entries_file"; then
    log "${YL}No files.conf found$RESET for ${BL}$source$RESET"
    pause_admin
    return
  fi
  if [ ! -s "$entries_file" ]; then
    log "${YL}No files listed$RESET in ${BL}$source$RESET"
    pause_admin
    return
  fi

  local selection_file="$TMP/${source}_file_choices"
  >"$selection_file"
  while IFS=';' read -r stored dest; do
    [ -z "$stored" ] && continue
    [ -z "$dest" ] && continue
    local repo_file="$BASE/configs/$source/files/$stored"
    local display="$dest (${stored})"
    echo "$stored|$dest|$repo_file"$'\t'"$display" >>"$selection_file"
  done <"$entries_file"
  if [ ! -s "$selection_file" ]; then
    log "${YL}No file artifacts found$RESET for ${BL}$source$RESET"
    pause_admin
    return
  fi

  local preview_cmd="bash -c 'line=\"\$1\"; data=\$(printf \"%s\" \"\$line\" | cut -f1); file=\${data##*|}; if [ -f \"\$file\" ]; then sed -n \"1,160p\" \"\$file\"; else echo \"File not found: \$file\"; fi' _ {}"
  local selected_lines=()
  if ! mapfile -t selected_lines < <(fzf --multi --with-nth=2 --prompt="files> " --header="Select file(s) from ${source}" --preview="$preview_cmd" --height=80% <"$selection_file"); then
    log "No files selected."
    pause_admin
    return
  fi
  if [ "${#selected_lines[@]}" -eq 0 ]; then
    log "No files selected."
    pause_admin
    return
  fi

  local destination
  destination=$(select_destination_config "$source")
  if [ -z "$destination" ]; then
    log "Abort"
    pause_admin
    return
  fi

  local action
  if ! action=$(menu "Transfer mode" "Move (remove from ${source})" "Copy (keep in ${source})"); then
    pause_admin
    return
  fi
  local move_mode=false
  if [ "${action%%:*}" = "1" ]; then
    move_mode=true
  fi

  local transferred=0
  for line in "${selected_lines[@]}"; do
    [ -z "$line" ] && continue
    local data=${line%%$'\t'*}
    IFS='|' read -r stored dest repo <<<"$data"
    if [ -z "$stored" ] || [ -z "$dest" ]; then
      continue
    fi
    if [ ! -f "$repo" ]; then
      warn "Source file ${BL}$repo$RESET missing - skipping."
      continue
    fi
    local existing_stored
    existing_stored=$(find_stored_for_target "$destination" "$dest")
    local dest_stored
    local dest_file
    local skip=false
    if [ -n "$existing_stored" ]; then
      dest_stored="$existing_stored"
      dest_file="$BASE/configs/$destination/files/$existing_stored"
      while true; do
        local conflict
        conflict=$(menu "Destination ${destination} already has ${dest}" "Overwrite with source" "Skip" "View diff")
        case "${conflict%%:*}" in
        "1")
          mkdir -p "$(dirname "$dest_file")"
          cp "$repo" "$dest_file"
          break
          ;;
        "2")
          skip=true
          break
          ;;
        "3")
          if [ -f "$dest_file" ]; then
            show_file_diff_viewer "$dest_file" "$repo"
          else
            warn "Destination file $dest_file missing."
          fi
          ;;
        *)
          ;;
        esac
      done
      if [ "$skip" = true ]; then
        continue
      fi
    else
      dest_stored=$(sanitize_rel_path "$dest")
      dest_file="$BASE/configs/$destination/files/$dest_stored"
      mkdir -p "$(dirname "$dest_file")"
      cp "$repo" "$dest_file"
      ensure_file_mapping_entry "$destination" "$dest_stored" "$dest"
    fi

    if [ "$move_mode" = true ]; then
      remove_file_mapping_entry "$source" "$stored" "$dest"
      rm -f "$repo"
      log "${YL}Moved${RESET} ${BL}$dest$RESET from ${source} -> ${destination}"
    else
      log "${GN}Copied${RESET} ${BL}$dest$RESET from ${source} -> ${destination}"
    fi
    ((transferred = transferred + 1))
  done

  if [ "$transferred" -eq 0 ]; then
    log "${YL}No files were transferred.$RESET"
  else
    log "${GN}$transferred file(s) transferred$RESET from ${BL}$source$RESET to ${BL}$destination$RESET"
  fi
  pause_admin
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
    move_files_between_configs
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
