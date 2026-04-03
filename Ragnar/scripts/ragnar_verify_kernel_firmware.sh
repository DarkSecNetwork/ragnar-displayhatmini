#!/bin/bash
# Pi kernel/bootloader vs running modules; brcmfmac firmware; reinstall on real mismatch; reboot flag.
set -uo pipefail

REBOOT_FLAG=/var/run/ragnar-reboot-required
LOG="${RAGNAR_MITIGATION_LOG:-/var/log/ragnar-mitigations.log}"
SKIP="${RAGNAR_SKIP_KERNEL_REINSTALL:-0}"

echo "=== Ragnar kernel / firmware enforcement ==="
mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
mkdir -p "$(dirname "$REBOOT_FLAG")" 2>/dev/null || true

if [[ "$SKIP" == "1" ]]; then
  echo "RAGNAR_SKIP_KERNEL_REINSTALL=1 — skipping kernel enforcement"
  exit 0
fi

if ! dpkg -s raspberrypi-kernel &>/dev/null; then
  echo "⚠ Mitigated: raspberrypi-kernel not installed (not Raspberry Pi OS?)"
  exit 0
fi

RUNNING="$(uname -r)"
MODPATH="/lib/modules/${RUNNING}"
KERNEL_MISMATCH=0

if [[ ! -d "$MODPATH" ]]; then
  echo "✖ Mismatch: missing $MODPATH"
  KERNEL_MISMATCH=1
elif ! dpkg-query -L raspberrypi-kernel 2>/dev/null | grep -qF "$MODPATH"; then
  echo "✖ Mismatch: running kernel not from installed raspberrypi-kernel package paths"
  KERNEL_MISMATCH=1
else
  echo "✔ Fixed: running kernel matches installed raspberrypi-kernel"
fi

if command -v vcgencmd >/dev/null 2>&1; then
  echo "--- vcgencmd version ---"
  vcgencmd version 2>/dev/null || true
fi

BRCM_OK=0
for pat in brcmfmac43430-sdio.bin brcmfmac43436-sdio.bin brcmfmac43455-sdio.bin; do
  if find /lib/firmware/brcm -name "$pat" 2>/dev/null | head -1 | grep -q .; then
    BRCM_OK=1
    break
  fi
done
if [[ "$BRCM_OK" -eq 0 ]]; then
  echo "⚠ Installing firmware-brcm80211 ( SDIO blob missing )"
  apt-get update -y || true
  apt-get install -y firmware-brcm80211 2>/dev/null || true
  BRCM_OK=0
  for pat in brcmfmac43430-sdio.bin brcmfmac43436-sdio.bin brcmfmac43455-sdio.bin; do
    if find /lib/firmware/brcm -name "$pat" 2>/dev/null | head -1 | grep -q .; then
      BRCM_OK=1
      break
    fi
  done
  if [[ "$BRCM_OK" -eq 0 ]]; then
    echo "⚠ Mitigated: firmware blobs still missing after package install"
  fi
fi

if [[ "$KERNEL_MISMATCH" -eq 1 ]]; then
  echo "Applying kernel/bootloader reinstall due to mismatch..."
  apt-get update -y || true
  if apt-get install --reinstall -y raspberrypi-bootloader raspberrypi-kernel; then
    touch "$REBOOT_FLAG"
    echo "RAGNAR: reboot required — kernel/bootloader reinstalled ($(date -Is))" | tee -a "$LOG"
    echo "✔ Mitigated: packages reinstalled; created $REBOOT_FLAG"
  else
    echo "✖ Limitation: kernel reinstall failed"
    echo "$(date -Is) KERNEL REINSTALL FAILED" >>"$LOG" 2>/dev/null || true
  fi
else
  rm -f "$REBOOT_FLAG" 2>/dev/null || true
fi

echo "=== Kernel / firmware step done ==="
exit 0
