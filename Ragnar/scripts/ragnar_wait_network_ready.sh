#!/bin/bash
# Wait until Wi-Fi: UP, IPv4, then connectivity (NM "full" or ICMP). Stops NM fallback AP first so client can associate.
# On failure: /var/run/ragnar-network-degraded + optional NM hotspot (ragnar_fallback_ap.sh).
set -uo pipefail

SEC="${RAGNAR_NET_WAIT_SEC:-120}"
IFACE="${RAGNAR_NET_IFACE:-}"
LOG="${RAGNAR_MITIGATION_LOG:-/var/log/ragnar-mitigations.log}"
DEGRADED_FLAG="${RAGNAR_NETWORK_DEGRADED_FLAG:-/var/run/ragnar-network-degraded}"
PING_HOST="${RAGNAR_CONNECTIVITY_PING:-1.1.1.1}"

SDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "$IFACE" ]]; then
  IFACE=$(iw dev 2>/dev/null | awk '$1=="Interface"{print $2; exit}')
  [[ -n "$IFACE" ]] || IFACE=wlan0
fi

echo "=== Ragnar network readiness (iface=${IFACE}, budget=${SEC}s, ping=${PING_HOST}) ==="
mkdir -p "$(dirname "$LOG")" "$(dirname "$DEGRADED_FLAG")" 2>/dev/null || true

# Recovery: always tear down a previous-boot NM hotspot so STA can try (single radio).
if [[ -x "$SDIR/ragnar_fallback_ap.sh" ]]; then
  bash "$SDIR/ragnar_fallback_ap.sh" stop 2>/dev/null || true
fi

START=$(date +%s)
DEADLINE=$(( START + SEC ))

_log() { echo "$1" | tee -a "$LOG" 2>/dev/null || echo "$1"; }

_connectivity_ok() {
  if command -v nmcli >/dev/null 2>&1; then
    local c
    c=$(nmcli networking connectivity check 2>/dev/null || echo "none")
    if [[ "$c" == "full" ]]; then
      return 0
    fi
  fi
  if command -v ping >/dev/null 2>&1; then
    ping -c1 -W2 "$PING_HOST" >/dev/null 2>&1 && return 0
  fi
  return 1
}

# Prefer NM connectivity wait; shares deadline with iface loop.
if command -v nm-online >/dev/null 2>&1; then
  REM=$(( DEADLINE - $(date +%s) ))
  [[ $REM -lt 1 ]] && REM=1
  if nm-online -t "$REM" -q 2>/dev/null; then
    _log "$(date -Is) nm-online: reported connectivity within budget"
  else
    _log "$(date -Is) nm-online: no full connectivity yet (continuing with iface + ping checks)"
  fi
fi

while [[ $(date +%s) -lt $DEADLINE ]]; do
  link_ok=0
  if ip link show dev "$IFACE" 2>/dev/null | grep -q 'state UP' || ip link show dev "$IFACE" 2>/dev/null | grep -q 'state UNKNOWN'; then
    link_ok=1
  fi
  if [[ "$link_ok" -eq 1 ]] && ip -4 addr show dev "$IFACE" 2>/dev/null | grep -q 'inet '; then
    if _connectivity_ok; then
      echo "✔ Fixed: ${IFACE} has IPv4 and connectivity (NM full or ping ${PING_HOST})"
      ip -4 addr show dev "$IFACE"
      _log "$(date -Is) network ready ${IFACE} (connectivity OK)"
      rm -f "$DEGRADED_FLAG" 2>/dev/null || true
      exit 0
    fi
  fi
  sleep 1
done

echo "[✖] Network not ready after ${SEC}s — ${IFACE} (no IPv4 or no route to internet)"
_log "$(date -Is) [✖] Network not ready after ${SEC}s — degraded (${IFACE})"
touch "$DEGRADED_FLAG" 2>/dev/null || true
echo "Created ${DEGRADED_FLAG} (Ragnar may retry / alert)"

if [[ -x "$SDIR/ragnar_fallback_ap.sh" ]] && [[ "${RAGNAR_DISABLE_FALLBACK_AP:-0}" != "1" ]]; then
  bash "$SDIR/ragnar_fallback_ap.sh" start || echo "⚠ Fallback AP script failed (see log)"
else
  echo "⚠ Fallback AP skipped (RAGNAR_DISABLE_FALLBACK_AP=1 or script missing)"
fi

exit 1
