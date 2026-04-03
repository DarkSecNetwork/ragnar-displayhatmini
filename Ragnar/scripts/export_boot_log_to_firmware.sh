#!/bin/bash
# Write this boot's kernel + journal text to the FAT boot partition under Boot_Log/
# (e.g. E:\\Boot_Log\\ragnar-boot-2026-03-27_14-30-00.log on Windows) without mounting ext4.
# Keeps only the 3 newest timestamped full logs (ragnar-boot-YYYY-MM-DD_*.log). Installed by install_ragnar.sh;
# triggered by ragnar-boot-log-to-firmware.service (runs as root).
#
# Also writes latest-boot-errors.log (errors only, overwritten each boot).
#
# Env (optional):
#   RAGNAR_BOOT_LOG_DIR       Directory on boot FAT (default: <boot>/Boot_Log)
#   RAGNAR_BOOT_LOG_KEEP      Number of full log files to retain (default: 3)
# Does not use set -e: must exit 0 so systemd does not mark the unit failed if the FS is ro.
set -uo pipefail

MAX_BYTES=450000
MAX_BYTES_ERRORS=200000
KEEP="${RAGNAR_BOOT_LOG_KEEP:-3}"
# Timestamped full logs only (must not match latest-boot-errors.log)
GLOB_FULL='ragnar-boot-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_*.log'

_boot_fw_dir() {
  if [[ -d /boot/firmware ]]; then
    echo /boot/firmware
  elif [[ -d /boot ]]; then
    echo /boot
  else
    echo ""
  fi
}

_prune_old_logs() {
  local dir="$1"
  local keep="$2"
  shopt -s nullglob
  local -a files=( "$dir"/$GLOB_FULL )
  shopt -u nullglob
  ((${#files[@]} <= keep)) && return 0
  local -a sorted
  mapfile -t sorted < <(ls -1t "${files[@]}" 2>/dev/null || true)
  ((${#sorted[@]} <= keep)) && return 0
  local i
  for ((i = keep; i < ${#sorted[@]}; i++)); do
    rm -f "${sorted[i]}"
  done
}

FW="$(_boot_fw_dir)"
if [[ -z "$FW" ]] || [[ ! -w "$FW" ]]; then
  echo "export_boot_log_to_firmware: no writable boot partition (skip)" >&2
  exit 0
fi

LOGDIR="${RAGNAR_BOOT_LOG_DIR:-$FW/Boot_Log}"
if ! mkdir -p "$LOGDIR" 2>/dev/null; then
  echo "export_boot_log_to_firmware: cannot create $LOGDIR (skip)" >&2
  exit 0
fi
chmod 755 "$LOGDIR" 2>/dev/null || true

# Timestamp: FAT + Windows friendly (no ':' in name)
STAMP="$(date +%Y-%m-%d_%H-%M-%S)"
OUT="$LOGDIR/ragnar-boot-${STAMP}.log"
TMP="$(mktemp)"

{
  echo "=== Ragnar boot log export ==="
  echo "Generated: $(date -Is)"
  echo "Hostname: $(hostname 2>/dev/null || echo unknown)"
  echo "Kernel: $(uname -r 2>/dev/null || echo unknown)"
  echo
  echo "=== dmesg (kernel ring buffer) ==="
  if command -v dmesg >/dev/null 2>&1; then
    dmesg -T 2>/dev/null || dmesg 2>/dev/null || true
  fi
  echo
  echo "=== journalctl -b (this boot, all priorities) ==="
  if command -v journalctl >/dev/null 2>&1; then
    journalctl -b --no-pager -o short-iso 2>/dev/null || true
  else
    echo "(journalctl not available)"
  fi
} >"$TMP" || true

sz=$(wc -c <"$TMP" 2>/dev/null | tr -d ' ' || echo 0)
if [[ "${sz:-0}" -gt "$MAX_BYTES" ]]; then
  echo "=== (truncated, last ${MAX_BYTES} bytes) ===" >"${TMP}.tail"
  tail -c "$MAX_BYTES" "$TMP" >>"${TMP}.tail"
  mv "${TMP}.tail" "$TMP"
fi

if ! mv "$TMP" "$OUT" 2>/dev/null; then
  rm -f "$TMP" 2>/dev/null || true
  echo "export_boot_log_to_firmware: failed to write $OUT" >&2
  exit 0
fi
chmod 644 "$OUT" 2>/dev/null || true

# Single file: error-priority lines only; overwritten every export (not rotated).
ERR_OUT="$LOGDIR/latest-boot-errors.log"
ERR_TMP="$(mktemp)"
JERR=""
if command -v journalctl >/dev/null 2>&1; then
  JERR=$(journalctl -b -p err --no-pager -o short-iso 2>/dev/null || true)
fi
DERR=""
DMESG_LEVEL_OK=0
if command -v dmesg >/dev/null 2>&1 && dmesg -h 2>&1 | grep -q -- '--level'; then
  DMESG_LEVEL_OK=1
  DERR=$(dmesg --level=err -T 2>/dev/null || true)
fi
{
  echo "=== Ragnar: errors from latest boot (overwritten each export) ==="
  echo "Generated: $(date -Is)"
  echo "Hostname: $(hostname 2>/dev/null || echo unknown)"
  echo
  echo "=== journalctl -b -p err (emerg, alert, crit, err) ==="
  if ! command -v journalctl >/dev/null 2>&1; then
    echo "(journalctl not available)"
  elif [[ -n "${JERR//[$' \t\r\n']/}" ]]; then
    printf '%s\n' "$JERR"
  else
    echo "(no error-priority journal lines this boot)"
  fi
  echo
  echo "=== dmesg --level=err ==="
  if ! command -v dmesg >/dev/null 2>&1; then
    echo "(dmesg not available)"
  elif [[ "$DMESG_LEVEL_OK" -eq 0 ]]; then
    echo "(dmesg --level=err not supported; see full timestamped log)"
  elif [[ -n "${DERR//[$' \t\r\n']/}" ]]; then
    printf '%s\n' "$DERR"
  else
    echo "(no dmesg err-level lines)"
  fi
} >"$ERR_TMP" || true

esz=$(wc -c <"$ERR_TMP" 2>/dev/null | tr -d ' ' || echo 0)
if [[ "${esz:-0}" -gt "$MAX_BYTES_ERRORS" ]]; then
  {
    echo "=== (truncated, last ${MAX_BYTES_ERRORS} bytes) ==="
    tail -c "$MAX_BYTES_ERRORS" "$ERR_TMP"
  } >"${ERR_TMP}.cap"
  mv "${ERR_TMP}.cap" "$ERR_TMP"
fi

if mv "$ERR_TMP" "$ERR_OUT" 2>/dev/null; then
  chmod 644 "$ERR_OUT" 2>/dev/null || true
else
  rm -f "$ERR_TMP" 2>/dev/null || true
  echo "export_boot_log_to_firmware: failed to write $ERR_OUT" >&2
fi

_prune_old_logs "$LOGDIR" "$KEEP"

echo "export_boot_log_to_firmware: wrote $OUT ($(wc -c <"$OUT" | tr -d ' ') bytes); $ERR_OUT; keeping ${KEEP} newest full logs in $LOGDIR"
exit 0
