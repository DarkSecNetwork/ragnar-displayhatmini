#!/bin/bash
# Bluetooth: non-blocking stabilization — rfkill, restarts, retries; always exit 0; degraded clearly logged.
set -uo pipefail

LOG="${RAGNAR_MITIGATION_LOG:-/var/log/ragnar-mitigations.log}"
echo "=== Ragnar Bluetooth (non-blocking) ==="
mkdir -p "$(dirname "$LOG")" 2>/dev/null || true

_try() {
  rfkill unblock bluetooth 2>/dev/null || true
  if systemctl list-unit-files 2>/dev/null | grep -q '^bluetooth.service'; then
    systemctl restart bluetooth.service 2>/dev/null || true
  fi
  sleep 2
  if command -v bluetoothctl >/dev/null 2>&1; then
    bluetoothctl show 2>/dev/null | grep -q 'Powered: yes' && return 0
  fi
  return 1
}

if ! command -v rfkill >/dev/null 2>&1; then
  echo "⚠ DEGRADED Bluetooth: rfkill missing (apt install rfkill)"
  echo "$(date -Is) BT DEGRADED no rfkill" >>"$LOG" 2>/dev/null || true
  exit 0
fi

rfkill list 2>/dev/null || true
rfkill unblock bluetooth 2>/dev/null || true

round=1
ok=0
while [[ $round -le 3 ]]; do
  if _try; then
    echo "✔ Fixed: Bluetooth powered after attempt ${round}"
    ok=1
    break
  fi
  echo "⚠ Bluetooth: retry ${round}/3 after delay..."
  sleep 3
  round=$((round + 1))
done

if [[ "$ok" -eq 0 ]]; then
  echo "⚠ DEGRADED Bluetooth: adapter not ready after retries — boot continues (see journalctl -u bluetooth)"
  echo "$(date -Is) BT DEGRADED after retries" >>"$LOG" 2>/dev/null || true
fi

exit 0
