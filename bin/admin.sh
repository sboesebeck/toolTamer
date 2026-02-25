if [ ! -e $BASE ]; then
  err "no config dir found - plase call $(dirname $0)/tt to create a default"
  exit 1
fi

function fixDuplicates() {

  cd $BASE/configs || return
  local config
  config=$(ls | fzf_themed --prompt="Select config for duplicate cleanup> ")

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
    local desc=""
    case "$reason" in
    parent:*)
      local parent=${reason#parent:}
      log "  [$pkgtype] ${BL}$pkg$RESET already exists in ${CN}$parent$RESET"
      desc="[$pkgtype] $pkg (in parent $parent)"
      ;;
    local)
      log "  [$pkgtype] ${BL}$pkg$RESET is listed multiple times in ${CN}$config$RESET"
      desc="[$pkgtype] $pkg (duplicated locally)"
      ;;
    esac
    echo "$pkgtype;$pkg;$reason;$desc" >>"$display"
  done <"$report"

  local chosen_lines=()
  if ! mapfile -t chosen_lines < <(cat "$display" | fzf_themed --multi --delimiter=';' --with-nth=4 --prompt="remove> " --header="Select duplicates to remove from ${config} (TAB to toggle, CTRL-A for all, ESC to cancel)"); then
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
  pkgs=$(cat $BASE/configs/$HOST/to_install.$INSTALLER | fzf_themed)
  cd $BASE/configs
  dest=$(ls -1 | fzf_themed)
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

function package_exists_in_file() {
  local pkg="$1"
  local file="$2"
  [ -f "$file" ] || return 1
  awk -v target="$pkg" '
  function trim(str) {
    sub(/^[ \t]+/, "", str)
    sub(/[ \t]+$/, "", str)
    return str
  }
  {
    line=$0
    sub(/#.*$/, "", line)
    line=trim(line)
    if (line == target) {
      found=1
      exit
    }
  }
  END {
    exit(found ? 0 : 1)
  }
  ' "$file"
}

function add_package_to_file() {
  local pkg="$1"
  local file="$2"
  touch "$file"
  if package_exists_in_file "$pkg" "$file"; then
    return 1
  fi
  echo "$pkg" >>"$file"
}

function remove_package_from_file() {
  local pkg="$1"
  local file="$2"
  [ -f "$file" ] || return 1
  local tmp="${file}.tmp"
  awk -v target="$pkg" '
  function trim(str) {
    sub(/^[ \t]+/, "", str)
    sub(/[ \t]+$/, "", str)
    return str
  }
  {
    line=$0
    stripped=line
    sub(/#.*$/, "", stripped)
    stripped=trim(stripped)
    if (stripped == target) {
      next
    }
    print line
  }
  ' "$file" >"$tmp"
  if cmp -s "$file" "$tmp"; then
    rm -f "$tmp"
    return 1
  fi
  mv "$tmp" "$file"
  return 0
}

function promote_or_copy_package_hierarchy() {
  local source
  source=$(list_available_configs | fzf_themed --prompt="Source config> ")
  if [ -z "$source" ]; then
    return
  fi

  local source_file="$BASE/configs/$source/to_install.$INSTALLER"
  if [ ! -f "$source_file" ]; then
    err "No package list found for $source ($INSTALLER)"
    return
  fi

  local pkg_list
  pkg_list=$(awk '
  function trim(str) {
    sub(/^[ \t]+/, "", str)
    sub(/[ \t]+$/, "", str)
    return str
  }
  {
    line=$0
    sub(/#.*$/, "", line)
    line=trim(line)
    if (line != "") {
      print line
    }
  }
  ' "$source_file" | sort -u)

  if [ -z "$pkg_list" ]; then
    warn "No packages available in $source"
    return
  fi

  local pkgs
  pkgs=$(printf "%s\n" "$pkg_list" | fzf_themed -m --prompt="Select package(s)> ")
  if [ -z "$pkgs" ]; then
    log "No packages selected."
    return
  fi

  local action
  if ! action=$(menu "Package hierarchy action" "Move to ${BL}parent$RESET config (upper)" "Copy to other ${BL}configs$RESET (branches)" "Cancel"); then
    return
  fi
  local choice=${action%%:*}

  case "$choice" in
  "1")
    local parents
    parents=$(list_parent_configs_for "$source")
    if [ -z "$parents" ]; then
      warn "No parent configs found for $source"
      return
    fi
    local dest
    dest=$(printf "%s\n" "$parents" | fzf_themed --prompt="Move to parent> ")
    if [ -z "$dest" ]; then
      return
    fi
    local dest_file="$BASE/configs/$dest/to_install.$INSTALLER"
    local moved=0
    local skipped=0
    for p in $pkgs; do
      if add_package_to_file "$p" "$dest_file"; then
        log "Added ${BL}$p$RESET to ${CN}$dest$RESET"
      else
        log "Already in ${CN}$dest$RESET: ${BL}$p$RESET"
      fi
      if remove_package_from_file "$p" "$source_file"; then
        log "Removed ${BL}$p$RESET from ${CN}$source$RESET"
        ((moved = moved + 1))
      else
        log "Not found in ${CN}$source$RESET: ${BL}$p$RESET"
        ((skipped = skipped + 1))
      fi
    done
    log "${GN}Move complete$RESET (${moved} moved, ${skipped} skipped)"
    ;;
  "2")
    local dests
    dests=$(list_available_configs | awk -v src="$source" '$0 != src' | fzf_themed -m --prompt="Copy to configs> " --header="Select destinations (TAB to toggle)")
    if [ -z "$dests" ]; then
      return
    fi
    local copied=0
    local exists=0
    for d in $dests; do
      local dest_file="$BASE/configs/$d/to_install.$INSTALLER"
      for p in $pkgs; do
        if add_package_to_file "$p" "$dest_file"; then
          log "Copied ${BL}$p$RESET to ${CN}$d$RESET"
          ((copied = copied + 1))
        else
          ((exists = exists + 1))
        fi
      done
    done
    log "${GN}Copy complete$RESET (${copied} added, ${exists} already present)"
    ;;
  *)
    return
    ;;
  esac
}
function showConfig() {
  rm -f $TMP/install_check
  cd $BASE/configs
  l=$(ls | fzf_themed)
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
  done | fzf_themed --reverse
}

function show_package_diff_viewer() {
  checkSystem
  echo "Checking installed packages using $INSTALLER..."
  : >$TMP/to_install
  getInstalledPackages $TMP/to_install $TMP/installed
  : >$TMP/missing
  : >$TMP/exceed

  while IFS= read -r l; do
    [ -z "$l" ] && continue
    if ! grep -Fxq "$l" $TMP/installed; then
      echo "$l" >>$TMP/missing
    fi
  done <$TMP/to_install
  sort -u $TMP/missing -o $TMP/missing

  while IFS= read -r l; do
    [ -z "$l" ] && continue
    if ! grep -Fxq "$l" $TMP/to_install; then
      echo "$l" >>$TMP/exceed
    fi
  done <$TMP/installed
  sort -u $TMP/exceed -o $TMP/exceed

  if [ ! -s "$TMP/missing" ] && [ ! -s "$TMP/exceed" ]; then
    log "${GN}All in sync$RESET — no differences found"
    return
  fi

  local pkg_lines=()
  while IFS= read -r pkg; do
    [ -z "$pkg" ] && continue
    pkg_lines+=("MISSING|${pkg}|  ✗  MISSING   ${pkg}")
  done <$TMP/missing
  while IFS= read -r pkg; do
    [ -z "$pkg" ] && continue
    pkg_lines+=("EXCESS|${pkg}|  ⊕  EXCESS    ${pkg}")
  done <$TMP/exceed

  local preview_cmd
  if [ "$INSTALLER" = "brew" ]; then
    preview_cmd='bash -c "pkg=\$(echo {} | cut -d\"|\" -f2); brew info \"\$pkg\" 2>/dev/null || echo \"No info for \$pkg\""'
  else
    preview_cmd='bash -c "pkg=\$(echo {} | cut -d\"|\" -f2); apt-cache show \"\$pkg\" 2>/dev/null || echo \"No info for \$pkg\""'
  fi

  while true; do
    local result
    result=$(printf "%s\n" "${pkg_lines[@]}" | fzf_themed \
      --multi \
      --delimiter='|' --with-nth=3 \
      --preview="$preview_cmd" \
      --preview-label=" Package Info " \
      --preview-window=right:50%:wrap \
      --border-label=" Package Differences " \
      --expect="f1,f3,f5,f7" \
      --header=$'F1=install missing  F3=remove excess  F5=add to TT  F7=remove from TT\nTAB=multi-select  ESC=back\n') || break

    local key selected
    key=$(echo "$result" | head -1)
    selected=$(echo "$result" | tail -n +2)
    [ -z "$selected" ] && continue

    case "$key" in
    f1)
      local to_act=""
      while IFS= read -r line; do
        [ -z "$line" ] && continue
        local cat pkg
        cat=$(echo "$line" | cut -d'|' -f1)
        pkg=$(echo "$line" | cut -d'|' -f2)
        if [ "$cat" = "MISSING" ]; then
          to_act="$to_act $pkg"
        else
          log "${YL}Skipping$RESET $pkg (not a missing package)"
        fi
      done <<<"$selected"
      to_act=$(echo "$to_act" | xargs)
      if [ -n "$to_act" ]; then
        log "${GN}Installing$RESET: $to_act"
        $INSTALL $to_act
      fi
      break
      ;;
    f3)
      local to_act=""
      while IFS= read -r line; do
        [ -z "$line" ] && continue
        local cat pkg
        cat=$(echo "$line" | cut -d'|' -f1)
        pkg=$(echo "$line" | cut -d'|' -f2)
        if [ "$cat" = "EXCESS" ]; then
          to_act="$to_act $pkg"
        else
          log "${YL}Skipping$RESET $pkg (not an excess package)"
        fi
      done <<<"$selected"
      to_act=$(echo "$to_act" | xargs)
      if [ -n "$to_act" ]; then
        log "${YL}Removing$RESET: $to_act"
        $UNINSTALL $to_act
      fi
      break
      ;;
    f5)
      local added=0
      while IFS= read -r line; do
        [ -z "$line" ] && continue
        local cat pkg
        cat=$(echo "$line" | cut -d'|' -f1)
        pkg=$(echo "$line" | cut -d'|' -f2)
        if [ "$cat" = "EXCESS" ]; then
          echo "$pkg" >>$BASE/configs/$HOST/to_install.$INSTALLER
          log "${GN}Added$RESET $pkg to ToolTamer"
          ((added = added + 1))
        else
          log "${YL}Skipping$RESET $pkg (not an excess package)"
        fi
      done <<<"$selected"
      log "${GN}$added package(s) added to ToolTamer$RESET"
      break
      ;;
    f7)
      local removed=0
      while IFS= read -r line; do
        [ -z "$line" ] && continue
        local cat pkg
        cat=$(echo "$line" | cut -d'|' -f1)
        pkg=$(echo "$line" | cut -d'|' -f2)
        if [ "$cat" = "MISSING" ]; then
          for c in common $(<$BASE/configs/$HOST/includes.conf) $HOST; do
            local cfg="$BASE/configs/$c/to_install.$INSTALLER"
            [ -f "$cfg" ] || continue
            if grep -Fxq "$pkg" "$cfg"; then
              grep -Fxv "$pkg" "$cfg" >"$cfg.tmp" && mv "$cfg.tmp" "$cfg"
              log "${YL}Removed$RESET $pkg from $c/to_install.$INSTALLER"
            fi
          done
          ((removed = removed + 1))
        else
          log "${YL}Skipping$RESET $pkg (not a missing package)"
        fi
      done <<<"$selected"
      log "${GN}$removed package(s) removed from ToolTamer$RESET"
      break
      ;;
    *)
      continue
      ;;
    esac
  done
  log "\n${GN}done.$RESET"
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

function show_file_diff_colored() {
  local repo="$1"
  local target="$2"
  if command -v difft >/dev/null 2>&1; then
    difft --color=always "$repo" "$target"
  else
    diff -u --color=always "$repo" "$target"
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
  selection=$(fzf_themed --border-label=" Choose file to add " --preview='[ -f {} ] && sed -n "1,200p" "{}"' --height=80%) || {
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
  dest_config=$(printf "%s\n" "${config_choices[@]}" | fzf_themed --prompt="config> " --header="Select destination config for $selection") || {
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

# Classify a file relative to $HOME against all TT configs.
# Prints: "identical:<config>" / "modified:<config>:<repo_file>" / "new"
# Returns 0 if tracked, 1 if new, 2 if system file missing.
function classify_file() {
  local rel="$1"
  local sys_file="$HOME/$rel"
  [ -f "$sys_file" ] || { echo "missing"; return 2; }

  while IFS= read -r cfg; do
    [ -z "$cfg" ] && continue
    local conf_file="$BASE/configs/$cfg/files.conf"
    [ -f "$conf_file" ] || continue
    while IFS=';' read -r stored dest; do
      [ -z "$stored" ] && continue
      [[ "$stored" =~ ^# ]] && continue
      dest=$(echo "$dest" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
      if [ "$dest" = "$rel" ]; then
        local repo_file="$BASE/configs/$cfg/files/$stored"
        if [ -f "$repo_file" ]; then
          local repo_hash sys_hash
          repo_hash=$(shasum <"$repo_file")
          sys_hash=$(shasum <"$sys_file")
          if [ "$repo_hash" = "$sys_hash" ]; then
            echo "identical:$cfg"
          else
            echo "modified:$cfg:$repo_file"
          fi
        else
          echo "missing_repo:$cfg:$stored"
        fi
        return 0
      fi
    done <"$conf_file"
  done < <(ls -1 "$BASE/configs")
  echo "new"
  return 1
}

# Process a single file through the add/check pipeline.
# $1 = absolute path to file
function process_single_file() {
  local abs="$1"
  if [ ! -f "$abs" ]; then
    err "File not found: $abs"
    return 1
  fi

  # Ensure file is under $HOME
  case "$abs" in
    "$HOME"/*) ;;
    *)
      err "File $abs is outside \$HOME — not supported by ToolTamer."
      return 1
      ;;
  esac

  local rel="${abs#$HOME/}"
  local classification
  classification=$(classify_file "$rel")

  case "$classification" in
  identical:*)
    local cfg="${classification#identical:}"
    log "${GN}✓$RESET $rel is up to date in config ${BL}$cfg$RESET"
    ;;
  modified:*)
    local cfg repo_file
    cfg=$(echo "$classification" | cut -d: -f2)
    repo_file=$(echo "$classification" | cut -d: -f3-)
    log "${YL}Modified$RESET $rel (config ${BL}$cfg$RESET)"
    local action
    while true; do
      action=$(menu "Action for $rel (config: $cfg)" \
        "${BL}U${RESET}pdate ToolTamer (system → repo)" \
        "${BL}R${RESET}evert (repo → system)" \
        "${BL}D${RESET}iff" \
        "${BL}S${RESET}kip") || return
      case "${action%%:*}" in
      "1"|"U"|"u")
        cp "$abs" "$repo_file"
        log "${GN}Updated$RESET ${repo_file##$BASE/configs/} from system"
        break
        ;;
      "2"|"R"|"r")
        cp "$repo_file" "$abs"
        log "${YL}Reverted$RESET $abs from ToolTamer"
        break
        ;;
      "3"|"D"|"d")
        show_file_diff_viewer "$repo_file" "$abs"
        # loop back to menu
        ;;
      *)
        log "Skipped $rel"
        break
        ;;
      esac
    done
    ;;
  new)
    log "${CN}New file$RESET $rel — not yet tracked"
    local config_choices=()
    while IFS= read -r cfg; do
      [ -z "$cfg" ] && continue
      config_choices+=("$cfg")
    done < <(list_available_configs)
    local dest_config
    dest_config=$(printf "%s\n" "${config_choices[@]}" | fzf_themed \
      --prompt="config> " \
      --border-label=" Select config for $rel ") || {
      log "Skipped $rel"
      return
    }
    [ -z "$dest_config" ] && { log "Skipped $rel"; return; }
    add_file_to_config_store "$dest_config" "$abs" "$rel"
    ;;
  *)
    warn "Unexpected classification '$classification' for $rel"
    ;;
  esac
}

# Recursively scan a directory, classify files, and present fzf batch UI.
# $1 = absolute path to directory
function process_directory_batch() {
  local dir="$1"
  if [ ! -d "$dir" ]; then
    err "Directory not found: $dir"
    return 1
  fi

  case "$dir" in
    "$HOME"/*) ;;
    *)
      err "Directory $dir is outside \$HOME — not supported by ToolTamer."
      return 1
      ;;
  esac

  local dir_rel="${dir#$HOME/}"
  log "Scanning ${BL}$dir_rel$RESET ..."

  # Collect files, apply excludes
  local files=()
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    files+=("$f")
  done < <(find "$dir" -type f \
    ! -path '*/.git/*' ! -path '*/.svn/*' ! -path '*/.hg/*' \
    ! -path '*/node_modules/*' ! -path '*/__pycache__/*' ! -path '*/.cache/*' \
    ! -name '*.swp' ! -name '*.swo' ! -name '*~' ! -name '.DS_Store' \
    2>/dev/null | sort)

  if [ ${#files[@]} -eq 0 ]; then
    log "No files found in $dir_rel"
    return
  fi

  # Classify each file
  local fzf_lines=()
  local new_count=0 mod_count=0 identical_count=0
  for f in "${files[@]}"; do
    local rel="${f#$HOME/}"
    local classification
    classification=$(classify_file "$rel")
    case "$classification" in
    identical:*)
      ((identical_count++)) || true
      ;;
    modified:*)
      local repo_file cfg
      repo_file=$(echo "$classification" | cut -d: -f3-)
      cfg=$(echo "$classification" | cut -d: -f2)
      fzf_lines+=("MOD|$f|$repo_file|$cfg|[MOD] $rel ($cfg)")
      ((mod_count++)) || true
      ;;
    new)
      fzf_lines+=("NEW|$f|||[NEW] $rel")
      ((new_count++)) || true
      ;;
    esac
  done

  log "Found: ${GN}$identical_count identical$RESET, ${YL}$mod_count modified$RESET, ${CN}$new_count new$RESET"

  if [ ${#fzf_lines[@]} -eq 0 ]; then
    log "${GN}All files in $dir_rel are up to date$RESET"
    return
  fi

  # fzf multi-select
  local selected
  selected=$(printf "%s\n" "${fzf_lines[@]}" | fzf_themed \
    --multi \
    --delimiter='|' --with-nth=5 \
    --border-label=" Add files from $dir_rel " \
    --header=$'TAB=multi-select  ENTER=process selected\n') || return

  [ -z "$selected" ] && return

  # Separate NEW and MOD
  local new_files=() mod_files=()
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    local type
    type=$(echo "$line" | cut -d'|' -f1)
    if [ "$type" = "NEW" ]; then
      new_files+=("$line")
    else
      mod_files+=("$line")
    fi
  done <<<"$selected"

  # Process NEW files: single config selection for entire batch
  if [ ${#new_files[@]} -gt 0 ]; then
    log "Adding ${CN}${#new_files[@]} new$RESET file(s)..."
    local config_choices=()
    while IFS= read -r cfg; do
      [ -z "$cfg" ] && continue
      config_choices+=("$cfg")
    done < <(list_available_configs)
    local dest_config
    dest_config=$(printf "%s\n" "${config_choices[@]}" | fzf_themed \
      --prompt="config> " \
      --border-label=" Select config for new files ") || {
      log "Skipping new files"
      dest_config=""
    }
    if [ -n "$dest_config" ]; then
      for line in "${new_files[@]}"; do
        local abs
        abs=$(echo "$line" | cut -d'|' -f2)
        local rel="${abs#$HOME/}"
        add_file_to_config_store "$dest_config" "$abs" "$rel"
      done
    fi
  fi

  # Process MOD files: action menu
  if [ ${#mod_files[@]} -gt 0 ]; then
    log "Processing ${YL}${#mod_files[@]} modified$RESET file(s)..."
    local action
    action=$(menu "Action for ${#mod_files[@]} modified file(s)" \
      "${BL}U${RESET}pdate ToolTamer (system → repo)" \
      "${BL}R${RESET}evert all (repo → system)" \
      "${BL}D${RESET}iff each, then decide" \
      "${BL}S${RESET}kip all") || return
    case "${action%%:*}" in
    "1"|"U"|"u")
      for line in "${mod_files[@]}"; do
        local abs repo_file
        abs=$(echo "$line" | cut -d'|' -f2)
        repo_file=$(echo "$line" | cut -d'|' -f3)
        cp "$abs" "$repo_file"
        log "${GN}Updated$RESET ${repo_file##$BASE/configs/}"
      done
      ;;
    "2"|"R"|"r")
      for line in "${mod_files[@]}"; do
        local abs repo_file
        abs=$(echo "$line" | cut -d'|' -f2)
        repo_file=$(echo "$line" | cut -d'|' -f3)
        cp "$repo_file" "$abs"
        log "${YL}Reverted$RESET ${abs#$HOME/}"
      done
      ;;
    "3"|"D"|"d")
      for line in "${mod_files[@]}"; do
        local abs
        abs=$(echo "$line" | cut -d'|' -f2)
        process_single_file "$abs"
      done
      ;;
    *)
      log "Skipped all modified files"
      ;;
    esac
  fi
}

# Entry point for tt --add. Processes each argument as file or directory.
# Usage: handle_add_command file1 [file2] [dir1] ...
function handle_add_command() {
  if [ $# -eq 0 ]; then
    err "Usage: tt --add FILE|DIR [FILE|DIR ...]"
    return 1
  fi

  for arg in "$@"; do
    # Resolve to absolute path
    local abs
    if [[ "$arg" = /* ]]; then
      abs="$arg"
    else
      abs="$(pwd)/$arg"
    fi
    # Resolve symlinks
    if command -v realpath >/dev/null 2>&1; then
      abs=$(realpath "$abs" 2>/dev/null) || abs="$abs"
    fi

    if [ -f "$abs" ]; then
      process_single_file "$abs"
    elif [ -d "$abs" ]; then
      process_directory_batch "$abs"
    else
      err "Not found: $arg"
    fi
  done
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
  selection=$(printf "%s\n" "${options[@]}" | fzf_themed --with-nth=2.. --prompt="destination> " --header="Select destination config") || {
    echo ""
    return
  }
  echo "${selection%%$'\t'*}"
}

function reviewManagedFileDiffs() {
  createEffectiveFilesList $TMP/files.lst

  # Create preview script
  cat >"$TMP/diff_preview.sh" <<'PREVIEW_EOF'
#!/usr/bin/env bash
line="$1"
repo=$(echo "$line" | cut -d'|' -f1)
target=$(echo "$line" | cut -d'|' -f2)
if command -v difft >/dev/null 2>&1; then
  difft --color=always "$repo" "$target" 2>/dev/null
else
  diff -u --color=always "$repo" "$target" 2>/dev/null
fi
PREVIEW_EOF
  chmod +x "$TMP/diff_preview.sh"

  while true; do
    local fzf_lines=()
    local idx=0
    while IFS= read -r entry; do
      [ -z "$entry" ] && continue
      local repo="${entry%%;*}"
      local target="${entry##*;}"
      [ -z "$repo" ] || [ -z "$target" ] && continue
      [ ! -f "$repo" ] || [ ! -f "$target" ] && continue

      local repo_hash target_hash
      repo_hash=$(shasum <"$repo")
      target_hash=$(shasum <"$target")
      [ "$repo_hash" = "$target_hash" ] && continue

      # Size-based status indicator
      local repo_size target_size indicator
      repo_size=$(wc -c <"$repo")
      target_size=$(wc -c <"$target")
      if [ "$target_size" -gt "$repo_size" ]; then
        indicator="[+]"
      elif [ "$target_size" -lt "$repo_size" ]; then
        indicator="[-]"
      else
        indicator="[~]"
      fi

      local target_disp="${target#$HOME/}"
      [ "$target_disp" = "$target" ] || target_disp="~/$target_disp"
      local repo_disp="${repo##$BASE/configs/}"

      fzf_lines+=("${repo}|${target}|${indicator} ${target_disp}  ←→  ${repo_disp}")
      ((idx = idx + 1))
    done <$TMP/files.lst

    if [ "${#fzf_lines[@]}" -eq 0 ]; then
      log "${GN}All tracked files are in sync$RESET"
      return
    fi

    local result
    result=$(printf "%s\n" "${fzf_lines[@]}" | fzf_themed \
      --multi \
      --delimiter='|' --with-nth=3 \
      --preview="bash $TMP/diff_preview.sh {}" \
      --preview-label=" Diff Preview " \
      --preview-window=right:60%:wrap \
      --border-label=" File Differences " \
      --expect="ctrl-a,ctrl-r" \
      --header=$'ENTER=detail view  TAB=multi-select  ctrl-a=add to TT  ctrl-r=revert\n') || return

    local key selected_lines
    key=$(echo "$result" | head -1)
    selected_lines=$(echo "$result" | tail -n +2)

    if [ -z "$selected_lines" ]; then
      continue
    fi

    case "$key" in
    ctrl-a)
      # Add to ToolTamer: copy local → repo
      while IFS= read -r line; do
        [ -z "$line" ] && continue
        local repo target
        repo=$(echo "$line" | cut -d'|' -f1)
        target=$(echo "$line" | cut -d'|' -f2)
        cp "$target" "$repo"
        log "${GN}Copied$RESET $target -> $repo"
      done <<<"$selected_lines"
      pause_admin
      ;;
    ctrl-r)
      # Revert: copy repo → local
      while IFS= read -r line; do
        [ -z "$line" ] && continue
        local repo target
        repo=$(echo "$line" | cut -d'|' -f1)
        target=$(echo "$line" | cut -d'|' -f2)
        cp "$repo" "$target"
        log "${YL}Reverted$RESET $target from ToolTamer"
      done <<<"$selected_lines"
      pause_admin
      ;;
    *)
      # ENTER: detail view for single file
      local line
      line=$(echo "$selected_lines" | head -1)
      local repo target
      repo=$(echo "$line" | cut -d'|' -f1)
      target=$(echo "$line" | cut -d'|' -f2)
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
      ;;
    esac
  done
}

function move_files_between_configs() {
  local source
  source=$(ls -1 "$BASE/configs" | fzf_themed --prompt="source config> " --header="Choose config to move/copy files from")
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
  if ! mapfile -t selected_lines < <(fzf_themed --multi --with-nth=2 --prompt="files> " --header="Select file(s) from ${source}" --preview="$preview_cmd" --height=80% <"$selection_file"); then
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

# When sourced with TT_SOURCE_ONLY=1, only define functions — skip admin menu.
[ "${TT_SOURCE_ONLY:-}" = "1" ] && return 0

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
  if ! o=$(menu "---> ToolTamer Admin Menu <---" "Move ${BL}l${RESET}ocal file to ${BL}ToolTamer$RESET" "Move files between configs in ${BL}ToolTamer$RESET" "View ${BL}d${RESET}ifferences of files" "View differences of ${BL}i${RESET}nstalled tools" "Show ${BL}C${RESET}onfig" "${BL}F${RESET}ix duplicate packages" "${BL}G${RESET}it view" "Add ${BL}P${RESET}ackage to installation" "M${BL}o${RESET}ve installed package" "${BL}H${RESET}ierarchy package actions (move/copy)" "${YL}return$RESET (${BL}q${RESET}/${BL}r$RESET)"); then
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
    show_package_diff_viewer
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
  "10" | "h" | "H")
    promote_or_copy_package_hierarchy
    pause_admin
    ;;
  "11" | "q" | "Q" | "r")
    return
    ;;
  esac
done
