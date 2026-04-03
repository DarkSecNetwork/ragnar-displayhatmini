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
  # Optional: timestamped copies for multi-run forensics (set RAGNAR_BOOT_BACKUP_VERSIONED=1).
  if [[ "${RAGNAR_BOOT_BACKUP_VERSIONED:-0}" == "1" ]]; then
    local ts
    ts=$(date -u +%Y%m%dT%H%M%SZ 2>/dev/null || echo "unknown")
    for f in "$fw/config.txt" "$fw/cmdline.txt"; do
      [[ -f "$f" ]] || continue
      cp -a "$f" "${f}.ragnar.${ts}.bak" 2>/dev/null && echo "Versioned backup: ${f}.ragnar.${ts}.bak"
    done
    if [[ "$(ragnar_boot_firmware_dir)" == "/boot/firmware" ]] && [[ -f /boot/config.txt ]]; then
      f="/boot/config.txt"
      cp -a "$f" "${f}.ragnar.${ts}.bak" 2>/dev/null && echo "Versioned backup: ${f}.ragnar.${ts}.bak"
    fi
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

# General installer log (same file as gpu_mem; tag [install]).
ragnar_install_log() {
  local ts msg logf
  msg="$*"
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "unknown-time")
  logf="${RAGNAR_INSTALLER_LOG:-/var/log/ragnar-installer.log}"
  if [[ -w "$(dirname "$logf")" ]] 2>/dev/null; then
    echo "[$ts] [install] $msg" >>"$logf"
  fi
}

# Flush boot partition writes (vfat) before long-running or risky steps.
ragnar_boot_partition_sync() {
  sync
}

# Abort early if firmware boot files are missing — never create a fake config.txt.
ragnar_installer_require_boot_files() {
  local fw
  fw="$(ragnar_boot_firmware_dir)"
  if [[ ! -f "$fw/config.txt" ]]; then
    echo "FATAL: $fw/config.txt not found — refusing to invent boot configuration." >&2
    return 1
  fi
  if [[ ! -f "$fw/cmdline.txt" ]]; then
    echo "FATAL: $fw/cmdline.txt not found." >&2
    return 1
  fi
  return 0
}

# Append one exact line if file exists and line not present (never create empty config.txt).
ragnar_config_append_line_if_missing_safe() {
  local line="$1" file="$2"
  [[ -f "$file" ]] || return 0
  grep -qxF "$line" "$file" 2>/dev/null || echo "$line" >>"$file"
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

# Append one kernel parameter to cmdline.txt if not already set (single-line cmdline only).
# Safe to call after ragnar_boot_backup; validates with ragnar_validate_cmdline_file when available.
ragnar_cmdline_append_if_missing() {
  local param="$1"
  local cl fw
  fw="$(ragnar_boot_firmware_dir)"
  cl="$fw/cmdline.txt"
  [[ -f "$cl" ]] || cl="/boot/cmdline.txt"
  [[ -f "$cl" ]] || return 0

  local content
  content=$(tr -d '\r' <"$cl" | head -1)
  if [[ " $content " == *" $param "* ]]; then
    return 0
  fi
  # If param is key=value, skip when that key is already present (avoid duplicate keys).
  if [[ "$param" == *"="* ]]; then
    local key="${param%%=*}"
    if grep -qE "(^|[[:space:]])${key}=" <<<"$content"; then
      return 0
    fi
  fi

  printf '%s %s\n' "$content" "$param" > "${cl}.ragnar.new" && mv "${cl}.ragnar.new" "$cl"

  if command -v ragnar_validate_cmdline_file >/dev/null 2>&1; then
    if ! ragnar_validate_cmdline_file "$cl"; then
      echo "ERROR: cmdline invalid after append: $param — restoring backup if present." >&2
      [[ -f "${cl}.ragnar.bak" ]] && cp -a "${cl}.ragnar.bak" "$cl"
      return 1
    fi
  fi
  echo "  cmdline: appended $param"
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

# -----------------------------------------------------------------------------
# GPU memory (gpu_mem=) — production installer path
# Dynamic RAM detection, mode-based defaults, caps, logging, per-step recovery.
# Env: RAGNAR_INSTALLER_GPU_MEM=<n|skip|min>  min = firmware minimum (~16), skip = remove line
#      RAGNAR_INSTALLER_LOG=/var/log/ragnar-installer.log
# -----------------------------------------------------------------------------

ragnar_installer_log() {
  local ts msg
  msg="$*"
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "unknown-time")
  local logf="${RAGNAR_INSTALLER_LOG:-/var/log/ragnar-installer.log}"
  if [[ -w "$(dirname "$logf")" ]] 2>/dev/null; then
    echo "[$ts] [gpu_mem] $msg" >>"$logf"
  fi
  echo "  [gpu_mem] $msg" >&2
}

# Total RAM in MB (Linux); empty if unknown.
ragnar_probe_mem_total_mb() {
  if [[ -r /proc/meminfo ]]; then
    awk '/^MemTotal:/ { printf "%.0f\n", $2/1024 }' /proc/meminfo
    return
  fi
  echo ""
}

# One-line board model (trailing NUL stripped).
ragnar_probe_device_model() {
  local m="unknown"
  if [[ -r /proc/device-tree/model ]]; then
    m=$(tr -d '\0' </proc/device-tree/model)
  elif [[ -r /sys/firmware/devicetree/base/model ]]; then
    m=$(tr -d '\0' </sys/firmware/devicetree/base/model)
  fi
  printf '%s\n' "$m"
}

# First gpu_mem= value in file (digits only); empty if none.
ragnar_config_read_gpu_mem() {
  local f="$1"
  [[ -f "$f" ]] || { echo ""; return; }
  grep -E '^[[:space:]]*gpu_mem=' "$f" 2>/dev/null | head -1 | sed -n 's/^[[:space:]]*gpu_mem=\([0-9]*\).*/\1/p'
}

# Clamp desired gpu_mem (MB) to [16,256] and to at most total_ram_mb/4 (VC4 headroom for Linux).
ragnar_gpu_mem_clamp_for_ram() {
  local want="$1" ram_mb="$2"
  local min_g=16 max_g=256
  [[ "$want" =~ ^[0-9]+$ ]] || want=$min_g
  if [[ -z "$ram_mb" || ! "$ram_mb" =~ ^[0-9]+$ ]] || [[ "$ram_mb" -lt 128 ]]; then
    ram_mb=1024
  fi
  local cap=$((ram_mb / 4))
  [[ "$cap" -gt "$max_g" ]] && cap=$max_g
  [[ "$cap" -lt "$min_g" ]] && cap=$min_g
  [[ "$want" -lt "$min_g" ]] && want=$min_g
  [[ "$want" -gt "$cap" ]] && want=$cap
  echo "$want"
}

# Recommended gpu_mem from display mode + RAM.
ragnar_gpu_mem_default_recommended() {
  local ram_mb="$1" mode="${2:-epd}"
  local gm=64
  if [[ -z "$ram_mb" || ! "$ram_mb" =~ ^[0-9]+$ ]]; then
    ram_mb=1024
  fi
  case "$mode" in
    displayhatmini)
      if [[ "$ram_mb" -le 512 ]]; then gm=64
      elif [[ "$ram_mb" -le 1024 ]]; then gm=96
      elif [[ "$ram_mb" -le 2048 ]]; then gm=128
      else gm=160
      fi
      ;;
    headless)
      gm=16
      [[ "$ram_mb" -gt 512 ]] && gm=32
      ;;
    *)
      gm=32
      [[ "$ram_mb" -gt 512 ]] && gm=48
      ;;
  esac
  ragnar_gpu_mem_clamp_for_ram "$gm" "$ram_mb"
}

ragnar_validate_gpu_mem_sanity() {
  local gm="$1" ram_mb="$2"
  [[ "$gm" =~ ^[0-9]+$ ]] || return 1
  # Align with ragnar_gpu_mem_clamp_for_ram: max 256 MB; min 16 MB (firmware).
  if [[ "$gm" -lt 16 ]] || [[ "$gm" -gt 256 ]]; then
    return 1
  fi
  if [[ -n "$ram_mb" && "$ram_mb" =~ ^[0-9]+$ ]]; then
    local cap=$((ram_mb / 4))
    [[ "$cap" -gt 256 ]] && cap=256
    [[ "$gm" -gt "$cap" ]] && return 1
  fi
  return 0
}

ragnar_config_strip_gpu_mem() {
  local f
  for f in "$@"; do
    [[ -f "$f" ]] || continue
    sed -i '/^[[:space:]]*gpu_mem=/d' "$f"
  done
}

# Append one line if not already present (installer-local; no dependency on install_ragnar.sh).
ragnar_config_append_line() {
  local line="$1" file="$2"
  [[ -f "$file" ]] || return 1
  grep -qxF "$line" "$file" 2>/dev/null || echo "$line" >>"$file"
}

# Main: apply gpu_mem with backup snapshot, validation, restore on failure.
# Args: primary config path (e.g. /boot/firmware/config.txt), DISPLAY_MODE
ragnar_apply_gpu_mem_production() {
  local primary="${1:-/boot/firmware/config.txt}"
  local mode="${2:-epd}"
  local mirror="/boot/config.txt"
  local ram_mb model old_pri old_mir snap_pri snap_mir
  local gm="" err=0

  ram_mb=$(ragnar_probe_mem_total_mb)
  model=$(ragnar_probe_device_model)
  ragnar_installer_log "start model='${model}' ram_mb=${ram_mb:-unknown} display_mode=$mode RAGNAR_INSTALLER_GPU_MEM=${RAGNAR_INSTALLER_GPU_MEM:-<unset>}"

  old_pri=$(ragnar_config_read_gpu_mem "$primary")
  [[ -f "$mirror" ]] && old_mir=$(ragnar_config_read_gpu_mem "$mirror")

  # Per-step snapshots for recovery (full file — small)
  snap_pri="${primary}.ragnar.gpu-snap"
  snap_mir="${mirror}.ragnar.gpu-snap"
  [[ -f "$primary" ]] && cp -a "$primary" "$snap_pri"
  [[ -f "$mirror" ]] && cp -a "$mirror" "$snap_mir"

  ragnar_gpu_mem_restore_snap() {
    [[ -f "$snap_pri" ]] && cp -a "$snap_pri" "$primary"
    [[ -f "$mirror" ]] && [[ -f "$snap_mir" ]] && cp -a "$snap_mir" "$mirror"
    ragnar_installer_log "RECOVERED config.txt from .ragnar.gpu-snap (gpu_mem apply failed validation)"
  }

  if [[ -n "${RAGNAR_INSTALLER_GPU_MEM:-}" ]]; then
    case "${RAGNAR_INSTALLER_GPU_MEM}" in
      skip|none|SKIP|NONE)
        ragnar_config_strip_gpu_mem "$primary" "$mirror"
        ragnar_installer_log "user skip: removed gpu_mem lines (was primary=${old_pri:-none} mirror=${old_mir:-none})"
        rm -f "$snap_pri" "$snap_mir" 2>/dev/null || true
        return 0
        ;;
      min|MIN)
        gm=16
        ;;
    esac
    if [[ -z "$gm" && "${RAGNAR_INSTALLER_GPU_MEM}" =~ ^[0-9]+$ ]]; then
      gm="$RAGNAR_INSTALLER_GPU_MEM"
    elif [[ -z "$gm" ]]; then
      ragnar_installer_log "invalid RAGNAR_INSTALLER_GPU_MEM='${RAGNAR_INSTALLER_GPU_MEM}' — falling back to recommended"
      gm=""
    fi
  fi

  if [[ -z "$gm" ]]; then
    gm=$(ragnar_gpu_mem_default_recommended "$ram_mb" "$mode")
  fi

  gm=$(ragnar_gpu_mem_clamp_for_ram "$gm" "$ram_mb")

  if ! ragnar_validate_gpu_mem_sanity "$gm" "$ram_mb"; then
    ragnar_installer_log "sanity failed for gm=$gm ram=$ram_mb — clamping again"
    gm=$(ragnar_gpu_mem_clamp_for_ram 16 "$ram_mb")
  fi

  ragnar_config_strip_gpu_mem "$primary" "$mirror"
  ragnar_config_append_line "gpu_mem=${gm}" "$primary"
  [[ -f "$mirror" && "$primary" != "$mirror" ]] && ragnar_config_append_line "gpu_mem=${gm}" "$mirror"

  if ! ragnar_validate_config_txt "$primary" 2>/dev/null; then
    err=1
  elif [[ -f "$mirror" ]] && ! ragnar_validate_config_txt "$mirror" 2>/dev/null; then
    err=1
  elif ! ragnar_validate_gpu_mem_sanity "$gm" "$ram_mb"; then
    err=1
  fi

  if [[ "$err" -ne 0 ]]; then
    ragnar_gpu_mem_restore_snap
    rm -f "$snap_pri" "$snap_mir" 2>/dev/null || true
    ragnar_installer_log "ERROR: validation failed after write; restored pre-gpu_mem snapshot"
    return 1
  fi

  rm -f "$snap_pri" "$snap_mir" 2>/dev/null || true
  ragnar_installer_log "ok gpu_mem=${gm} (previous primary=${old_pri:-none}) — log ${RAGNAR_INSTALLER_LOG:-/var/log/ragnar-installer.log}"
  return 0
}
