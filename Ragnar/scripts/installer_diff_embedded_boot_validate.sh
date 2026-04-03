#!/usr/bin/env bash
# Compare embedded boot_validate.inc inside install_ragnar.sh to Ragnar/scripts/boot_validate.inc.
# Exit 0 if identical, 1 if mismatch or error. Run from CI or before release.
#
# Usage:
#   ./installer_diff_embedded_boot_validate.sh [path/to/install_ragnar.sh]
#
# Env:
#   INSTALLER_SCRIPT — override path to install_ragnar.sh
#   BOOT_VALIDATE_INC — override path to boot_validate.inc

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAGNAR_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${RAGNAR_DIR}/.." && pwd)"
INSTALLER="${INSTALLER_SCRIPT:-${1:-$REPO_ROOT/install_ragnar.sh}}"
INC="${BOOT_VALIDATE_INC:-$SCRIPT_DIR/boot_validate.inc}"

if [[ ! -f "$INSTALLER" ]]; then
  echo "FAIL: installer not found: $INSTALLER" >&2
  exit 1
fi
if [[ ! -f "$INC" ]]; then
  echo "FAIL: boot_validate.inc not found: $INC" >&2
  exit 1
fi

_tmp_embed="$(mktemp)"
cleanup() { rm -f "$_tmp_embed"; }
trap cleanup EXIT

awk '
  /^[[:space:]]*source \/dev\/stdin <<'\''BOOT_VALIDATE_INC'\''$/ { skip = 1; next }
  skip && /^BOOT_VALIDATE_INC$/ { exit }
  skip { print }
' "$INSTALLER" >"$_tmp_embed"

if [[ ! -s "$_tmp_embed" ]]; then
  echo "FAIL: could not extract embedded block (missing heredoc markers in $INSTALLER?)" >&2
  exit 1
fi

if diff -q "$_tmp_embed" "$INC" >/dev/null 2>&1; then
  echo "OK: embedded boot_validate.inc matches $(basename "$INC")"
  exit 0
fi

echo "FAIL: embedded heredoc differs from $INC" >&2
echo "       Fix: copy boot_validate.inc into the heredoc or release only from repo with matching files." >&2
diff -u "$INC" "$_tmp_embed" >&2 || true
exit 1
