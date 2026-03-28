#!/usr/bin/env bash
# Install systemd drop-in so pisugar-server starts after udev/I2C is ready (PiSugar 3).
# Idempotent. Safe to re-run after OS updates.
# Usage: sudo /home/ragnar/Ragnar/scripts/install_pisugar_boot_dropin.sh

set -euo pipefail

if [[ "${EUID:-0}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

DROPIN_DIR="/etc/systemd/system/pisugar-server.service.d"
UNIT_TEST=$(systemctl list-unit-files 'pisugar-server.service' 2>/dev/null | grep -c pisugar-server || true)
if [[ "$UNIT_TEST" -eq 0 ]] && ! systemctl cat pisugar-server.service >/dev/null 2>&1; then
  echo "SKIP: pisugar-server.service not installed (install PiSugar power manager first)." >&2
  exit 0
fi

mkdir -p "$DROPIN_DIR"
cat >"$DROPIN_DIR/10-ragnar-boot-order.conf" <<'EOF'
# Ragnar: PiSugar 3 — reduce I2C/TCP races on boot (merged with vendor unit)
[Unit]
After=systemd-udev-trigger.service systemd-modules-load.service local-fs.target

[Service]
# Wait for i2c-dev node (PiSugar battery MCU). Bounded poll, not a blind fixed sleep for the whole boot.
ExecStartPre=/bin/bash -c 'for _ in $(seq 1 120); do [[ -c /dev/i2c-1 ]] && exit 0; sleep 0.05; done; logger -t pisugar-prep "Ragnar: /dev/i2c-1 not ready after 6s — continuing (check dtparam=i2c_arm=on)"; exit 0'
EOF

systemctl daemon-reload
echo "Installed $DROPIN_DIR/10-ragnar-boot-order.conf"
echo "Restarting pisugar-server to apply ordering..."
systemctl restart pisugar-server.service 2>/dev/null || true
exit 0
