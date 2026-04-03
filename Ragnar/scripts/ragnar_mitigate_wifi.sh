#!/bin/bash
# Deterministic Wi-Fi baseline for Ragnar: NetworkManager / nmcli ONLY (no wpa_supplicant.conf).
# Always: bgscan off, stable MAC, country, P2P discouraged via NM where supported.
set -uo pipefail

R="${RAGNAR_WIFI_REG:-US}"
if [[ ! "$R" =~ ^[A-Z]{2}$ ]]; then
  R=$(grep -oE 'cfg80211\.ieee80211_regdom=([A-Z]{2})' /proc/cmdline 2>/dev/null | cut -d= -f2 || echo US)
  [[ "$R" =~ ^[A-Z]{2}$ ]] || R=US
fi

echo "=== Ragnar Wi-Fi baseline (NM-only, regdom=${R}) ==="

if ! command -v nmcli >/dev/null 2>&1; then
  echo "✖ Ragnar Wi-Fi: nmcli not found — install NetworkManager"
  exit 1
fi

systemctl start NetworkManager.service 2>/dev/null || true
if ! systemctl is-active --quiet NetworkManager.service 2>/dev/null; then
  echo "✖ Ragnar Wi-Fi: NetworkManager is not active"
  exit 1
fi

mkdir -p /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/99-ragnar-wifi-baseline.conf <<EOF
# Ragnar deterministic Wi-Fi: stable scan MAC; P2P off via nmcli per profile (p2p_disabled=1 equivalent); NM-only — no wpa_supplicant.conf
[device-wifi]
wifi.scan-rand-mac-address=no
EOF

# Kernel regulatory domain (complements NM country on connections)
if command -v iw >/dev/null 2>&1; then
  iw reg set "$R" 2>/dev/null || true
fi

NM_COUNT=0
while IFS= read -r uuid; do
  [[ -z "$uuid" ]] && continue
  nmcli connection modify "$uuid" wifi.bgscan 0 2>/dev/null || nmcli connection modify "$uuid" 802-11-wireless.bgscan 0 2>/dev/null || true
  nmcli connection modify "$uuid" 802-11-wireless.cloned-mac-address preserve 2>/dev/null || \
    nmcli connection modify "$uuid" wifi.cloned-mac-address preserve 2>/dev/null || true
  nmcli connection modify "$uuid" 802-11-wireless.country "$R" 2>/dev/null || true
  # Reduce P2P / Wi-Fi Direct probing where NM exposes it
  nmcli connection modify "$uuid" 802-11-wireless.p2p no 2>/dev/null || \
    nmcli connection modify "$uuid" wifi.p2p no 2>/dev/null || true
  NM_COUNT=$((NM_COUNT + 1))
  echo "  nmcli: baseline applied to $uuid"
done < <(nmcli -t -f UUID,TYPE connection show 2>/dev/null | awk -F: '$2=="802-11-wireless"{print $1}')

systemctl reload NetworkManager.service 2>/dev/null || true

echo "=== Ragnar Wi-Fi baseline done (Wi-Fi profiles updated: ${NM_COUNT}) ==="
exit 0
