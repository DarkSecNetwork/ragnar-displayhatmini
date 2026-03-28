#!/usr/bin/env bash
# PiSugar 3 / pisugar-server diagnostics for Ragnar on Raspberry Pi.
# Usage: sudo /home/ragnar/Ragnar/scripts/check_pisugar.sh

set -uo pipefail

PASS=0
FAIL=0
warn() { echo "WARN: $*"; }
bad() { echo "FAIL: $*"; FAIL=$((FAIL + 1)); }
ok() { echo "PASS: $*"; PASS=$((PASS + 1)); }

echo "=== PiSugar / pisugar-server check ($(date -Is 2>/dev/null || date)) ==="
echo

if [[ "${EUID:-0}" -ne 0 ]]; then
  echo "Some checks need root; run: sudo $0" >&2
fi

# --- systemd ---
if systemctl cat pisugar-server.service &>/dev/null; then
  ok "pisugar-server unit is present"
else
  bad "pisugar-server.service not installed (install PiSugar power manager)"
fi

if systemctl is-enabled pisugar-server &>/dev/null; then
  ok "pisugar-server is enabled"
else
  warn "pisugar-server is not enabled"
fi

if systemctl is-active pisugar-server &>/dev/null; then
  ok "pisugar-server is active"
else
  st=$(systemctl is-active pisugar-server 2>/dev/null || echo unknown)
  bad "pisugar-server is not active (state: $st)"
fi

DROPIN="/etc/systemd/system/pisugar-server.service.d/10-ragnar-boot-order.conf"
if [[ -f "$DROPIN" ]]; then
  ok "Ragnar boot drop-in present: $DROPIN"
else
  warn "Ragnar I2C drop-in missing — run: sudo /home/ragnar/Ragnar/scripts/install_pisugar_boot_dropin.sh"
fi

# --- I2C device ---
if [[ -c /dev/i2c-1 ]]; then
  ok "/dev/i2c-1 exists"
else
  bad "/dev/i2c-1 missing — enable I2C (raspi-config / boot config)"
fi

if command -v i2cdetect &>/dev/null && [[ -c /dev/i2c-1 ]]; then
  echo
  echo "--- i2cdetect -y 1 (PiSugar often 0x32 / 0x75 range; see vendor) ---"
  i2cdetect -y 1 2>/dev/null || warn "i2cdetect failed"
  echo
else
  warn "i2cdetect not installed or no bus — apt install i2c-tools"
fi

# --- TCP (pisugar Python client uses localhost; port varies by pisugar-server version) ---
if command -v ss &>/dev/null; then
  echo "--- ss -ltn (look for LISTEN on 127.0.0.1) ---"
  ss -ltn 2>/dev/null | head -25 || true
  echo
fi

# --- Journal (recent errors) ---
echo
echo "--- journalctl -u pisugar-server -b -p err..alert --no-pager (last 40 lines) ---"
if [[ "${EUID:-0}" -eq 0 ]]; then
  journalctl -u pisugar-server -b -p err..alert --no-pager 2>/dev/null | tail -40 || true
else
  warn "Need root for full journal"
fi

echo
echo "--- journalctl -u pisugar-server -b --no-pager | tail -25 ---"
if [[ "${EUID:-0}" -eq 0 ]]; then
  journalctl -u pisugar-server -b --no-pager 2>/dev/null | tail -25 || true
fi

echo
echo "--- grep -i pisugar (last boot, priority >= warning) ---"
if [[ "${EUID:-0}" -eq 0 ]]; then
  journalctl -b -p warning --no-pager 2>/dev/null | grep -i pisugar | tail -20 || echo "(no matches)"
else
  echo "(skipped — need root)"
fi

echo
echo "Summary: PASS=$PASS FAIL=$FAIL"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
