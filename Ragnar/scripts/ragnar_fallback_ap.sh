#!/bin/bash
# Ragnar fallback Wi-Fi AP via NetworkManager only (no hostapd/dnsmasq). Pi Zero 2 W: AP OR STA, not both.
# Usage: ragnar_fallback_ap.sh start|stop|status
set -uo pipefail

LOG="${RAGNAR_MITIGATION_LOG:-/var/log/ragnar-mitigations.log}"
CON_NAME="${RAGNAR_FALLBACK_AP_CON_NAME:-Ragnar-Setup}"
SSID="${RAGNAR_FALLBACK_AP_SSID:-Ragnar-Setup}"
PASS="${RAGNAR_FALLBACK_AP_PASSWORD:-ragnar123}"
IFACE="${RAGNAR_FALLBACK_AP_IFACE:-}"
MODE="${1:-start}"

mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
_log() { echo "$1" | tee -a "$LOG" 2>/dev/null || echo "$1"; }

if [[ -z "$IFACE" ]]; then
  IFACE=$(iw dev 2>/dev/null | awk '$1=="Interface"{print $2; exit}')
  [[ -n "$IFACE" ]] || IFACE=wlan0
fi

if ! command -v nmcli >/dev/null 2>&1; then
  echo "✖ ragnar_fallback_ap: nmcli not available"
  exit 1
fi

systemctl start NetworkManager.service 2>/dev/null || true

_stop() {
  echo "--- Ragnar fallback AP: stop (restore client mode on ${IFACE}) ---"
  if nmcli -t -f NAME connection show 2>/dev/null | grep -qx "$CON_NAME"; then
    nmcli connection down "$CON_NAME" 2>/dev/null || true
    _log "$(date -Is) fallback AP: connection down ${CON_NAME}"
  fi
  # Allow saved Wi-Fi profiles to take over again
  nmcli device set "$IFACE" managed yes 2>/dev/null || true
  nmcli radio wifi on 2>/dev/null || true
  echo "  Stopped ${CON_NAME} (if it was active)."
}

_start() {
  if [[ "${RAGNAR_DISABLE_FALLBACK_AP:-0}" == "1" ]]; then
    echo "⚠ RAGNAR_DISABLE_FALLBACK_AP=1 — skipping fallback AP"
    return 0
  fi

  echo "[⚠] Network failed → Starting fallback AP (${SSID})"
  _log "$(date -Is) [⚠] Starting fallback AP ${CON_NAME} on ${IFACE}"

  _stop

  if nmcli -t -f NAME connection show 2>/dev/null | grep -qx "$CON_NAME"; then
    echo "  Reusing existing NM profile: ${CON_NAME}"
    nmcli connection modify "$CON_NAME" connection.autoconnect no 2>/dev/null || true
    nmcli connection modify "$CON_NAME" ipv4.method shared 2>/dev/null || true
    nmcli connection modify "$CON_NAME" ipv6.method ignore 2>/dev/null || true
    if nmcli connection up "$CON_NAME" ifname "$IFACE" 2>/dev/null; then
      :
    else
      echo "  Existing profile failed to start; recreating hotspot..."
      nmcli connection delete "$CON_NAME" 2>/dev/null || true
      _create_hotspot
    fi
  else
    _create_hotspot
  fi

  nmcli connection modify "$CON_NAME" connection.autoconnect no 2>/dev/null || true

  local ip4
  ip4=$(ip -4 -o addr show dev "$IFACE" 2>/dev/null | awk '{print $4}' | head -1)
  echo "[✔] AP active: connect to SSID \"${SSID}\" (WPA2) — then SSH / web UI"
  echo "    IPv4 on ${IFACE}: ${ip4:-pending (NM shared, often 10.42.x.x)}"
  _log "$(date -Is) [✔] Fallback AP up ${CON_NAME} ${ip4:-unknown}"
  return 0
}

_create_hotspot() {
  # NetworkManager: single call creates hotspot + shared IPv4
  if ! nmcli device wifi hotspot ifname "$IFACE" con-name "$CON_NAME" ssid "$SSID" password "$PASS" 2>/dev/null; then
    echo "✖ nmcli device wifi hotspot failed (check regulatory domain / rfkill)"
    _log "$(date -Is) fallback AP: nmcli hotspot failed"
    return 1
  fi
  nmcli connection modify "$CON_NAME" connection.autoconnect no 2>/dev/null || true
  nmcli connection modify "$CON_NAME" ipv4.method shared 2>/dev/null || true
  nmcli connection modify "$CON_NAME" ipv6.method ignore 2>/dev/null || true
  return 0
}

_status() {
  if nmcli -t -f NAME,DEVICE connection show --active 2>/dev/null | grep -q "${CON_NAME}:.*${IFACE}"; then
    echo "active: ${CON_NAME} on ${IFACE}"
    ip -4 addr show dev "$IFACE"
  else
    echo "inactive: ${CON_NAME}"
  fi
}

case "$MODE" in
  start) _start ;;
  stop) _stop ;;
  status) _status ;;
  *) echo "Usage: $0 {start|stop|status}"; exit 1 ;;
esac
