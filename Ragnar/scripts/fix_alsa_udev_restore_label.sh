#!/bin/bash
# Fix systemd-udevd err: 90-alsa-restore.rules GOTO="alsa_restore_std" has no matching label.
# Stock file jumps to a label that must exist in the same rules file; some images ship without it.
# We copy to /etc, append LABEL=, and divert the /usr/lib copy so udev does not load two 90-alsa files.
set -uo pipefail

SRC=/usr/lib/udev/rules.d/90-alsa-restore.rules
[[ -f "$SRC" ]] || exit 0
grep -q 'GOTO="alsa_restore_std"' "$SRC" 2>/dev/null || exit 0
if grep -q '^LABEL="alsa_restore_std"' "$SRC" 2>/dev/null; then
  exit 0
fi
if [[ -f /etc/udev/rules.d/90-alsa-restore.rules ]] && grep -q '^LABEL="alsa_restore_std"' /etc/udev/rules.d/90-alsa-restore.rules 2>/dev/null; then
  exit 0
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "fix_alsa_udev_restore_label: run as root" >&2
  exit 1
fi

cp -a "$SRC" /etc/udev/rules.d/90-alsa-restore.rules
printf '\n# Ragnar: label target for GOTO=alsa_restore_std (same file as GOTO)\nLABEL="alsa_restore_std"\n' >> /etc/udev/rules.d/90-alsa-restore.rules

if command -v dpkg-divert >/dev/null 2>&1; then
  if [[ -f /usr/lib/udev/rules.d/90-alsa-restore.rules ]]; then
    dpkg-divert --add --rename --divert /usr/lib/udev/rules.d/90-alsa-restore.rules.distrib /usr/lib/udev/rules.d/90-alsa-restore.rules 2>/dev/null || true
  fi
fi

udevadm control --reload-rules 2>/dev/null || true
udevadm trigger --subsystem-match=sound --action=change 2>/dev/null || true
echo "fix_alsa_udev_restore_label: wrote /etc/udev/rules.d/90-alsa-restore.rules with LABEL=alsa_restore_std"
exit 0
