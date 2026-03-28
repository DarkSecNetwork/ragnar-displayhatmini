#!/usr/bin/env bash
# Validate Raspberry Pi boot files after Ragnar installer changes.
# Used by pre_reboot_check.sh; same rules as install_ragnar.sh (sources boot_validate.inc).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=boot_validate.inc
source "${SCRIPT_DIR}/boot_validate.inc"

if [[ "${EUID:-0}" -ne 0 ]]; then
  echo "Run as root for full access to /boot/firmware: sudo $0" >&2
  exit 1
fi

if ragnar_validate_boot_after_install; then
  echo "OK: boot files (config.txt / cmdline.txt) passed validation."
  exit 0
fi
echo "FAIL: boot file validation — fix cmdline/config or restore *.ragnar.bak" >&2
exit 1
