#!/bin/bash
# Safely repair dpkg-divert on 90-alsa-restore.rules if present (upgrade conflicts).
set -uo pipefail

echo "=== Ragnar ALSA udev divert repair ==="

if ! command -v dpkg-divert >/dev/null 2>&1; then
  exit 0
fi

if ! dpkg-divert --list 2>/dev/null | grep -q '90-alsa-restore.rules'; then
  echo "✔ Fixed: no dpkg-divert for 90-alsa-restore.rules"
  exit 0
fi

echo "Detected diversion:"
dpkg-divert --list 2>/dev/null | grep '90-alsa-restore.rules' || true

if [[ "${RAGNAR_ALSA_DIVERT_REPAIR:-0}" == "1" ]] || [[ "${RAGNAR_ALSA_DIVERT_REPAIR:-}" == "yes" ]]; then
  echo "RAGNAR_ALSA_DIVERT_REPAIR=1: removing divert and reinstalling alsa-utils..."
  dpkg-divert --remove --rename /usr/lib/udev/rules.d/90-alsa-restore.rules 2>/dev/null || \
    dpkg-divert --remove /usr/lib/udev/rules.d/90-alsa-restore.rules 2>/dev/null || true
  apt-get install --reinstall -y alsa-utils 2>/dev/null || echo "⚠ Mitigated: alsa-utils reinstall had warnings"
  udevadm control --reload-rules 2>/dev/null || true
  echo "✔ Fixed: divert removed and alsa-utils reinstalled (verify udev rules)"
  exit 0
fi

echo "⚠ Mitigated: divert present — to repair: sudo RAGNAR_ALSA_DIVERT_REPAIR=1 $0"
echo "   Or: sudo dpkg-divert --remove /usr/lib/udev/rules.d/90-alsa-restore.rules && sudo apt install --reinstall alsa-utils"
exit 0
