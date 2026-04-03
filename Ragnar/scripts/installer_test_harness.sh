#!/usr/bin/env bash
# Lightweight installer verification (run on dev PC or Raspberry Pi).
# Does not replace full SD soak tests — proves script coherence and validation logic.
#
# Usage:
#   ./installer_test_harness.sh [path/to/install_ragnar.sh]
#
# On Pi as root, also runs validate_boot_files.sh if present.
#
# Env:
#   SKIP_EMBEDDED_DIFF=1 — skip heredoc vs boot_validate.inc check
#   SKIP_MOCK_VALIDATION=1 — skip temp-dir validation unit checks

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAGNAR_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${RAGNAR_DIR}/.." && pwd)"
INSTALLER="${1:-$REPO_ROOT/install_ragnar.sh}"
BOOT_INC="$SCRIPT_DIR/boot_validate.inc"
FAILS=0

fail() { echo "FAIL: $*" >&2; FAILS=$((FAILS + 1)); }

echo "=== Ragnar installer test harness ==="
echo "Installer: $INSTALLER"
echo ""

if [[ ! -f "$INSTALLER" ]]; then
  echo "FAIL: installer not found" >&2
  exit 1
fi

if command -v bash >/dev/null 2>&1; then
  if bash -n "$INSTALLER"; then
    echo "OK: bash -n install_ragnar.sh"
  else
    fail "bash -n syntax error"
  fi
else
  echo "SKIP: bash not in PATH"
fi

if [[ "${SKIP_EMBEDDED_DIFF:-0}" != "1" ]] && [[ -x "$SCRIPT_DIR/installer_diff_embedded_boot_validate.sh" ]]; then
  if "$SCRIPT_DIR/installer_diff_embedded_boot_validate.sh" "$INSTALLER"; then
    echo "OK: embedded boot_validate.inc sync"
  else
    fail "embedded vs boot_validate.inc mismatch"
  fi
elif [[ "${SKIP_EMBEDDED_DIFF:-0}" != "1" ]]; then
  echo "SKIP: installer_diff_embedded_boot_validate.sh not executable"
fi

# --- Mock /boot for validation functions (no real firmware writes) ---
if [[ "${SKIP_MOCK_VALIDATION:-0}" != "1" ]] && [[ -f "$BOOT_INC" ]]; then
  _tdir="$(mktemp -d)"
  cleanup_td() { rm -rf "$_tdir"; }
  trap cleanup_td EXIT

  mkdir -p "$_tdir/boot/firmware"
  printf '%s\n' 'enable_uart=1' >"$_tdir/boot/firmware/config.txt"
  printf '%s\n' 'console=serial0,115200 root=PARTUUID=deadbeef rootfstype=ext4 rootwait quiet' >"$_tdir/boot/firmware/cmdline.txt"

  # shellcheck source=/dev/null
  source "$BOOT_INC"

  if ragnar_validate_config_txt "$_tdir/boot/firmware/config.txt" \
    && ragnar_validate_cmdline_file "$_tdir/boot/firmware/cmdline.txt"; then
    echo "OK: mock firmware files validate"
  else
    fail "mock validation should pass"
  fi

  echo 'garbage' >"$_tdir/boot/firmware/cmdline.txt"
  if ! ragnar_validate_cmdline_file "$_tdir/boot/firmware/cmdline.txt"; then
    echo "OK: invalid cmdline rejected"
  else
    fail "invalid cmdline should fail validation"
  fi

  rm -f "$_tdir/boot/firmware/cmdline.txt"
  printf '%s\n%s\n' 'line1' 'line2' >"$_tdir/boot/firmware/cmdline.txt"
  if ! ragnar_validate_cmdline_file "$_tdir/boot/firmware/cmdline.txt"; then
    echo "OK: multi-line cmdline rejected"
  else
    fail "multi-line cmdline should fail"
  fi

  if ragnar_validate_gpu_mem_sanity 64 512 && ! ragnar_validate_gpu_mem_sanity 300 512; then
    echo "OK: gpu_mem sanity bounds (64 OK, 300 excessive for 512MB RAM)"
  else
    fail "gpu_mem sanity unexpected"
  fi

  trap - EXIT
  rm -rf "$_tdir"
fi

# On-target: live boot partition check
if [[ "${EUID:-0}" -eq 0 ]] && [[ -d /boot/firmware ]] && [[ -x "$SCRIPT_DIR/validate_boot_files.sh" ]]; then
  if "$SCRIPT_DIR/validate_boot_files.sh"; then
    echo "OK: validate_boot_files.sh (live /boot/firmware)"
  else
    fail "validate_boot_files.sh on live system"
  fi
elif [[ "${EUID:-0}" -ne 0 ]]; then
  echo "SKIP: validate_boot_files.sh (run as root on Pi for live check)"
fi

echo ""
if [[ "$FAILS" -eq 0 ]]; then
  echo "=== HARNESS PASS ($FAILS failures) ==="
  exit 0
fi
echo "=== HARNESS FAIL ($FAILS failure(s)) ===" >&2
exit 1
