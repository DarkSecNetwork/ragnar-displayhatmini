#!/usr/bin/env bash
# Run full pre-reboot validation, then reboot. Never reboot if checks fail.
# Usage: sudo /home/ragnar/Ragnar/scripts/safe_reboot.sh

set -euo pipefail

readonly RAGNAR_SCRIPTS="/home/ragnar/Ragnar/scripts"
readonly PRE_CHECK="${RAGNAR_SCRIPTS}/pre_reboot_check.sh"
readonly LOG_FILE="/var/log/ragnar_health.log"

if [[ "${EUID:-0}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

if [[ ! -x "$PRE_CHECK" ]]; then
  echo "Missing or not executable: $PRE_CHECK" >&2
  exit 1
fi

ts="$(date -Is 2>/dev/null || date)"
if touch "$LOG_FILE" 2>/dev/null; then
  printf '%s safe_reboot.sh: invoking pre_reboot_check.sh\n' "$ts" >>"$LOG_FILE"
fi

if ! "$PRE_CHECK"; then
  ts="$(date -Is 2>/dev/null || date)"
  if touch "$LOG_FILE" 2>/dev/null; then
    printf '%s safe_reboot.sh: REBOOT DENIED (pre_reboot_check failed)\n' "$ts" >>"$LOG_FILE"
  fi
  echo "Reboot aborted. Fix issues above and check $LOG_FILE" >&2
  exit 2
fi

ts="$(date -Is 2>/dev/null || date)"
if touch "$LOG_FILE" 2>/dev/null; then
  printf '%s safe_reboot.sh: pre_reboot_check passed; calling /sbin/reboot\n' "$ts" >>"$LOG_FILE"
fi

exec /sbin/reboot
