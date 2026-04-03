#!/bin/bash
# Optional captive-portal helpers for Ragnar fallback AP (NetworkManager hotspot).
# NM "shared" mode often uses 10.42.x.x — NOT necessarily 192.168.4.x. Adjust IPs to match `ip -4 addr show dev wlan0`.
#
# Usage (as root): ragnar_captive_portal.sh install|remove|status
#
# "install" adds:
#   - iptables NAT: redirect TCP 80 → Ragnar web UI port (default 8000) on the AP interface
#   - A dnsmasq.d drop-in template for DNS hijack — MAY conflict with NM's internal dnsmasq; test on your image.
#
# WiFi join QR uses SSID/password from RAGNAR_FALLBACK_AP_* (see ragnar_fallback_ap.sh). Phones open HTTP after
# associating; redirect helps the dashboard appear without typing a URL.

set -euo pipefail

IFACE="${RAGNAR_CAPTIVE_IFACE:-wlan0}"
WEB_PORT="${RAGNAR_CAPTIVE_WEB_PORT:-8000}"
# Gateway IP on AP (detect if unset)
GW_IP="${RAGNAR_CAPTIVE_GW_IP:-}"
RULE_COMMENT="ragnar-captive-80"

_log() { echo "[ragnar_captive_portal] $*"; }

_detect_gw() {
  if [[ -n "$GW_IP" ]]; then
    echo "$GW_IP"
    return
  fi
  ip -4 -o addr show dev "$IFACE" 2>/dev/null | awk '{print $4}' | head -1 | cut -d/ -f1
}

_install_iptables() {
  command -v iptables >/dev/null 2>&1 || { _log "iptables not found"; return 1; }
  if iptables -t nat -C PREROUTING -i "$IFACE" -p tcp --dport 80 -j REDIRECT --to-ports "$WEB_PORT" 2>/dev/null; then
    _log "iptables rule already present"
    return 0
  fi
  iptables -t nat -A PREROUTING -i "$IFACE" -p tcp --dport 80 -j REDIRECT --to-ports "$WEB_PORT"
  _log "iptables: TCP/80 → $WEB_PORT on $IFACE"
}

_remove_iptables() {
  command -v iptables >/dev/null 2>&1 || return 0
  while iptables -t nat -D PREROUTING -i "$IFACE" -p tcp --dport 80 -j REDIRECT --to-ports "$WEB_PORT" 2>/dev/null; do
    :
  done
  _log "iptables: removed redirect on $IFACE"
}

_write_dnsmasq_snippet() {
  local ip="$1"
  local conf="/etc/dnsmasq.d/ragnar-captive.conf"
  _log "Writing $conf (review before enabling system dnsmasq; may conflict with NetworkManager)"
  cat <<EOF >"$conf"
# Ragnar captive DNS — all names → AP gateway (optional; requires standalone dnsmasq or NM hook)
# interface=$IFACE
# dhcp-range=10.42.0.10,10.42.0.100,12h
# address=/#/$ip
EOF
}

case "${1:-}" in
  install)
    if [[ $(id -u) -ne 0 ]]; then
      _log "Run as root: sudo $0 install"
      exit 1
    fi
    GW_IP=$(_detect_gw || true)
    if [[ -z "${GW_IP:-}" ]]; then
      _log "Could not detect IPv4 on $IFACE — set RAGNAR_CAPTIVE_GW_IP"
      exit 1
    fi
    _install_iptables
    _write_dnsmasq_snippet "$GW_IP"
    _log "Done. HTTP to port 80 on $IFACE redirects to port $WEB_PORT."
    _log "If captive DNS is needed, merge dnsmasq config with NM (see script comments)."
    ;;
  remove)
    if [[ $(id -u) -ne 0 ]]; then
      _log "Run as root"
      exit 1
    fi
    _remove_iptables
    rm -f /etc/dnsmasq.d/ragnar-captive.conf 2>/dev/null || true
    _log "Removed captive helpers"
    ;;
  status)
    if iptables -t nat -L PREROUTING -n -v 2>/dev/null | grep -q "dpt:80.*redir ports $WEB_PORT"; then
      _log "iptables redirect: present"
    else
      _log "iptables redirect: not found"
    fi
    ;;
  *)
    echo "Usage: $0 {install|remove|status}"
    exit 1
    ;;
esac
