#!/usr/bin/env bash
# Validate USB Ethernet gadget + SSH for headless Pi (e.g. Pi Zero 2 W over OTG).
# Run on the Pi: sudo /home/ragnar/Ragnar/scripts/check_usb_ssh.sh
# Expected static IP for usb0 is read from NetworkManager profile ragnar-usb-gadget if present,
# else from dhcpcd.conf for usb0, else env RAGNAR_USB_EXPECT_IP.

set -uo pipefail

PASS=0
FAIL=0

ok() {
  echo "PASS: $1"
  PASS=$((PASS + 1))
}

bad() {
  echo "FAIL: $1" >&2
  FAIL=$((FAIL + 1))
}

echo "=== check_usb_ssh.sh ($(date -Is)) ==="

# Kernel modules
if lsmod | grep -q '^dwc2'; then
  ok "kernel module dwc2 loaded"
else
  bad "dwc2 not loaded (need dtoverlay=dwc2 in config.txt + reboot)"
fi

if lsmod | grep -q '^g_ether'; then
  ok "kernel module g_ether loaded"
else
  bad "g_ether not loaded (need modules-load=dwc2,g_ether in cmdline.txt + reboot)"
fi

# Interface
if ip link show usb0 >/dev/null 2>&1; then
  ok "network interface usb0 exists"
  echo "    $(ip -4 -br addr show usb0 2>/dev/null || true)"
else
  bad "usb0 missing — use USB data port, data cable, dwc2+g_ether, then reboot"
fi

# Expected IP
EXPECT="${RAGNAR_USB_EXPECT_IP:-}"
if [[ -z "$EXPECT" ]] && command -v nmcli >/dev/null 2>&1; then
  EXPECT="$(nmcli -g ipv4.addresses connection show ragnar-usb-gadget 2>/dev/null | head -1 | cut -d/ -f1)"
fi
if [[ -z "$EXPECT" ]] && [[ -f /etc/dhcpcd.conf ]]; then
  EXPECT="$(grep -A20 '^interface usb0' /etc/dhcpcd.conf 2>/dev/null | grep 'static ip_address=' | sed -n 's/.*ip_address=\([0-9.]*\).*/\1/p' | head -1)"
fi

if [[ -n "$EXPECT" ]]; then
  got="$(ip -4 -br addr show usb0 2>/dev/null | awk '{print $3}' | cut -d/ -f1)"
  if [[ "$got" == "$EXPECT" ]]; then
    ok "usb0 IPv4 matches expected $EXPECT"
  else
    bad "usb0 IPv4 is '${got:-missing}', expected $EXPECT (set PC USB adapter to same subnet)"
  fi
else
  echo "SKIP: expected usb0 IP (set RAGNAR_USB_EXPECT_IP= or configure ragnar-usb-gadget / dhcpcd usb0)"
fi

# SSH
if systemctl is-active --quiet ssh 2>/dev/null || systemctl is-active --quiet sshd 2>/dev/null; then
  ok "ssh service active"
else
  bad "ssh/sshd service not active"
fi

if ss -tlnp 2>/dev/null | grep -q ':22 '; then
  ok "something listening on TCP port 22"
else
  bad "nothing listening on port 22"
fi

if [[ -f /etc/ssh/sshd_config ]]; then
  if grep -qE '^[[:space:]]*ListenAddress[[:space:]]+' /etc/ssh/sshd_config 2>/dev/null; then
    echo "WARN: ListenAddress set in sshd_config — SSH may not bind all interfaces:"
    grep -E '^[[:space:]]*ListenAddress' /etc/ssh/sshd_config || true
  else
    ok "sshd_config has no restrictive ListenAddress (default: all interfaces)"
  fi
fi

echo "--- summary: PASS=$PASS FAIL=$FAIL ---"
if [[ "$FAIL" -gt 0 ]]; then
  echo "See: docs/USB_SSH_GADGET.md (in repo) and ensure dwc2 + g_ether + usb0 static IP."
  exit 1
fi
exit 0
