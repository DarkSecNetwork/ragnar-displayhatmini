# shellcheck shell=bash
# Shared boot validation for Raspberry Pi OS (Bookworm /boot/firmware).
# Sourced by install_ragnar.sh and validate_boot_files.sh — keep logic in one place.

ragnar_boot_firmware_dir() {
  if [[ -d /boot/firmware ]]; then
    echo /boot/firmware
  else
    echo /boot
  fi
}

# Call once before any installer change to config.txt / cmdline.txt (preserves pre-Ragnar state).
ragnar_boot_backup() {
  local fw f
  fw="$(ragnar_boot_firmware_dir)"
  for f in "$fw/config.txt" "$fw/cmdline.txt"; do
    [[ -f "$f" ]] || continue
    [[ -f "${f}.ragnar.bak" ]] && continue
    if cp -a "$f" "${f}.ragnar.bak"; then
      echo "Backed up (restore point): ${f}.ragnar.bak"
    fi
  done
  # Legacy path: some images use only /boot/config.txt
  if [[ "$(ragnar_boot_firmware_dir)" == "/boot/firmware" ]] && [[ -f /boot/config.txt ]]; then
    f="/boot/config.txt"
    [[ -f "${f}.ragnar.bak" ]] || cp -a "$f" "${f}.ragnar.bak" 2>/dev/null && echo "Backed up: ${f}.ragnar.bak" || true
  fi
}

ragnar_boot_restore_from_bak() {
  local fw f
  fw="$(ragnar_boot_firmware_dir)"
  echo "Attempting restore from .ragnar.bak backups..."
  for f in "$fw/config.txt" "$fw/cmdline.txt"; do
    if [[ -f "${f}.ragnar.bak" ]] && [[ -f "$f" ]]; then
      cp -a "${f}.ragnar.bak" "$f" && echo "Restored $f from ${f}.ragnar.bak"
    fi
  done
  if [[ "$(ragnar_boot_firmware_dir)" == "/boot/firmware" ]] && [[ -f /boot/config.txt.ragnar.bak ]]; then
    cp -a /boot/config.txt.ragnar.bak /boot/config.txt && echo "Restored /boot/config.txt from .ragnar.bak"
  fi
}

# Returns 0 if cmdline looks valid for Raspberry Pi boot.
ragnar_validate_cmdline_file() {
  local f="$1"
  local line_count content

  [[ -f "$f" ]] || { echo "validate: missing $f" >&2; return 1; }

  line_count=$(grep -cve '^[[:space:]]*$' "$f" 2>/dev/null || echo 0)
  if [[ "$line_count" -ne 1 ]]; then
    echo "validate: $f must have exactly one non-empty line (found $line_count). Multi-line cmdline breaks Raspberry Pi boot." >&2
    return 1
  fi

  content=$(tr -d '\r' <"$f" | head -1)
  if [[ ! "$content" =~ (root=|PARTUUID=) ]]; then
    echo "validate: $f missing root= or PARTUUID= — possible corruption." >&2
    return 1
  fi

  if grep -q 'modules-load=dwc2,g_ether' <<<"$content"; then
    local n
    n=$(grep -o 'modules-load=dwc2,g_ether' <<<"$content" | wc -l | tr -d ' ')
    if [[ "${n:-0}" -gt 1 ]]; then
      echo "validate: duplicate modules-load=dwc2,g_ether in $f" >&2
      return 1
    fi
  fi

  # Avoid absurd line length (corruption)
  if [[ "${#content}" -gt 4096 ]]; then
    echo "validate: $f line unreasonably long (${#content} chars)" >&2
    return 1
  fi

  return 0
}

ragnar_validate_config_txt() {
  local f="$1"
  [[ -f "$f" ]] || { echo "validate: missing $f" >&2; return 1; }
  if ! grep -qE '^[[:space:]]*[^#[:space:]]' "$f" 2>/dev/null; then
    echo "validate: $f has no active settings (only comments?) — suspicious." >&2
    return 1
  fi
  return 0
}

# Run after all installer changes to /boot/firmware/* (and optional /boot/config.txt).
ragnar_validate_boot_after_install() {
  local fw err=0
  fw="$(ragnar_boot_firmware_dir)"

  ragnar_validate_config_txt "$fw/config.txt" || err=1
  ragnar_validate_cmdline_file "$fw/cmdline.txt" || err=1

  if [[ -f /boot/config.txt ]] && [[ "$fw" == "/boot/firmware" ]]; then
    ragnar_validate_config_txt /boot/config.txt || err=1
  fi

  return "$err"
}
