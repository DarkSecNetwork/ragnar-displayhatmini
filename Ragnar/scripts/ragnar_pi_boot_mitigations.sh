#!/bin/bash
# Deterministic Ragnar boot conditioning (every boot): NM Wi-Fi baseline, kernel/firmware,
# optional ALSA divert repair, then network readiness wait. Bluetooth: ragnar-mitigate-bluetooth.service.
# No journal-based reactive logic.
set -uo pipefail

RDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export RAGNAR_WIFI_REG="${RAGNAR_WIFI_REG:-US}"
export RAGNAR_NET_WAIT_SEC="${RAGNAR_NET_WAIT_SEC:-120}"
export RAGNAR_NET_IFACE="${RAGNAR_NET_IFACE:-}"
export RAGNAR_MITIGATION_LOG="${RAGNAR_MITIGATION_LOG:-/var/log/ragnar-mitigations.log}"

if [[ "$(id -u)" -eq 0 ]] && command -v apt-get >/dev/null 2>&1; then
  # Bound apt so a stuck dpkg lock cannot hang boot forever (mitigations unit has TimeoutStartSec too).
  timeout 180 apt-get install -y rfkill firmware-brcm80211 iw network-manager iputils-ping 2>/dev/null || true
fi

mkdir -p "$(dirname "$RAGNAR_MITIGATION_LOG")" 2>/dev/null || true
{
  echo "======== $(date -Is) ragnar_pi_boot_mitigations start ========"
} >>"$RAGNAR_MITIGATION_LOG" 2>/dev/null || true

echo "=========================================="
echo " Ragnar boot mitigations (deterministic)"
echo "=========================================="

echo ""
echo "--- [Wi-Fi baseline: nmcli only] ---"
if [[ -x "$RDIR/ragnar_mitigate_wifi.sh" ]]; then
  bash "$RDIR/ragnar_mitigate_wifi.sh" || echo "✖ Wi-Fi baseline reported failure"
fi

echo ""
echo "--- [Kernel / firmware] ---"
if [[ -x "$RDIR/ragnar_verify_kernel_firmware.sh" ]]; then
  bash "$RDIR/ragnar_verify_kernel_firmware.sh" || true
fi

if [[ -f /var/run/ragnar-reboot-required ]]; then
  echo ""
  echo "⚠ REBOOT REQUIRED: /var/run/ragnar-reboot-required exists (kernel/bootloader or firmware update)"
fi

echo ""
echo "--- [ALSA divert repair (optional env)] ---"
if [[ -x "$RDIR/ragnar_repair_alsa_divert.sh" ]]; then
  bash "$RDIR/ragnar_repair_alsa_divert.sh" || true
fi

echo ""
echo "--- [Network readiness] ---"
if [[ -x "$RDIR/ragnar_wait_network_ready.sh" ]]; then
  bash "$RDIR/ragnar_wait_network_ready.sh" || echo "⚠ Network readiness wait failed (see log)"
fi

{
  echo "======== $(date -Is) ragnar_pi_boot_mitigations end ========"
} >>"$RAGNAR_MITIGATION_LOG" 2>/dev/null || true

echo "=========================================="
echo " Summary: deterministic steps completed."
echo " Log: ${RAGNAR_MITIGATION_LOG}"
echo "=========================================="
exit 0
