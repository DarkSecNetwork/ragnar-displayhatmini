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

# Count I2C addresses that responded (not "--") on a bus.
i2c_addr_count() {
  local bus=$1
  [[ -c "/dev/i2c-${bus}" ]] || return 0
  i2cdetect -y "$bus" 2>/dev/null | awk '
    /^[0-9a-f]{2}:/ {
      for (i = 2; i <= NF; i++) {
        if ($i != "" && $i != "--") n++
      }
    }
    END { print n+0 }
  '
}

if command -v i2cdetect &>/dev/null; then
  echo
  for b in 1 2 0; do
    [[ -c "/dev/i2c-${b}" ]] || continue
    echo "--- i2cdetect -y ${b} (PiSugar RTC often 0x57; MCU varies by model) ---"
    i2cdetect -y "$b" 2>/dev/null || warn "i2cdetect -y ${b} failed"
    n=$(i2c_addr_count "$b")
    if [[ "${n:-0}" -eq 0 ]]; then
      warn "bus ${b}: no I2C devices detected (all --)"
    else
      ok "bus ${b}: ${n} address(es) responded"
    fi
    echo
  done
  n1=$(i2c_addr_count 1)
  if [[ "${n1:-0}" -eq 0 ]]; then
    bad "bus 1 empty — PiSugar cannot work (nothing at 0x57 etc.). Reseat stack, check 5V, or disable pisugar-server if no hardware: systemctl disable --now pisugar-server"
  fi
else
  warn "i2cdetect not installed — apt install i2c-tools"
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
