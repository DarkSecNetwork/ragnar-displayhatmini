#!/bin/bash
# Ragnar installer (Display HAT Mini, e-Paper, headless)
# Repo: https://github.com/DarkSecNetwork/ragnar-displayhatmini (installer on main branch)
# Download and run (correct URL includes main/):
#   wget https://raw.githubusercontent.com/DarkSecNetwork/ragnar-displayhatmini/main/install_ragnar.sh
#   sudo chmod +x install_ragnar.sh && sudo ./install_ragnar.sh
set -euo pipefail

USER_NAME="ragnar"
HOME_DIR="/home/${USER_NAME}"
RAGNAR_DIR="${HOME_DIR}/Ragnar"
CONFIG_TXT="/boot/firmware/config.txt"
# cmdline: Bookworm uses /boot/firmware/cmdline.txt (fallback /boot/cmdline.txt)
CMDLINE_TXT="/boot/firmware/cmdline.txt"
DISPLAY_SPI_HZ="60000000"
SELECTED_EPD="epd2in13_V4"
DISPLAY_MODE="epd"
RAGNAR_ENTRYPOINT="Ragnar.py"
INSTALL_PWN="n"
INSTALL_PISUGAR="n"
CONFIGURE_STATIC_IP="n"
STATIC_IP=""
ACTIVE_INTERFACE=""
# Display HAT Mini orientation (overridden when user picks portrait in select_display)
DISPLAYHATMINI_REF_W=320
DISPLAYHATMINI_REF_H=240
DISPLAYHATMINI_ROTATION=180

echo "========================================"
echo " Ragnar Installer v6.3"
echo "========================================"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this script with sudo."
  exit 1
fi

# Directory where this installer script lives (for local repo install)
INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Boot file backup / validation (Ragnar/scripts/boot_validate.inc); embedded fallback for wget-only install.
# shellcheck disable=SC1091
if [[ -f "$INSTALLER_DIR/Ragnar/scripts/boot_validate.inc" ]]; then
  source "$INSTALLER_DIR/Ragnar/scripts/boot_validate.inc"
elif [[ -f "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/Ragnar/scripts/boot_validate.inc" ]]; then
  source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/Ragnar/scripts/boot_validate.inc"
else
  source /dev/stdin <<'BOOT_VALIDATE_INC'
# shellcheck shell=bash
# Shared boot validation for Raspberry Pi OS (Bookworm /boot/firmware).
# Sourced by install_ragnar.sh and validate_boot_files.sh — keep logic in one place.

ragnar_boot_firmware_dir() {
  if [[ -d /boot/firmware ]]; then
    echo /boot/firmware
  else
    echo /boot
  fi
}

# Call once before any installer change to config.txt / cmdline.txt (preserves pre-Ragnar state).
ragnar_boot_backup() {
  local fw f
  fw="$(ragnar_boot_firmware_dir)"
  for f in "$fw/config.txt" "$fw/cmdline.txt"; do
    [[ -f "$f" ]] || continue
    [[ -f "${f}.ragnar.bak" ]] && continue
    if cp -a "$f" "${f}.ragnar.bak"; then
      echo "Backed up (restore point): ${f}.ragnar.bak"
    fi
  done
  if [[ "$(ragnar_boot_firmware_dir)" == "/boot/firmware" ]] && [[ -f /boot/config.txt ]]; then
    f="/boot/config.txt"
    [[ -f "${f}.ragnar.bak" ]] || cp -a "$f" "${f}.ragnar.bak" 2>/dev/null && echo "Backed up: ${f}.ragnar.bak" || true
  fi
}

ragnar_boot_restore_from_bak() {
  local fw f
  fw="$(ragnar_boot_firmware_dir)"
  echo "Attempting restore from .ragnar.bak backups..."
  for f in "$fw/config.txt" "$fw/cmdline.txt"; do
    if [[ -f "${f}.ragnar.bak" ]] && [[ -f "$f" ]]; then
      cp -a "${f}.ragnar.bak" "$f" && echo "Restored $f from ${f}.ragnar.bak"
    fi
  done
  if [[ "$(ragnar_boot_firmware_dir)" == "/boot/firmware" ]] && [[ -f /boot/config.txt.ragnar.bak ]]; then
    cp -a /boot/config.txt.ragnar.bak /boot/config.txt && echo "Restored /boot/config.txt from .ragnar.bak"
  fi
}

ragnar_validate_cmdline_file() {
  local f="$1"
  local line_count content
  [[ -f "$f" ]] || { echo "validate: missing $f" >&2; return 1; }
  line_count=$(grep -cve '^[[:space:]]*$' "$f" 2>/dev/null || echo 0)
  if [[ "$line_count" -ne 1 ]]; then
    echo "validate: $f must have exactly one non-empty line (found $line_count). Multi-line cmdline breaks Raspberry Pi boot." >&2
    return 1
  fi
  content=$(tr -d '\r' <"$f" | head -1)
  if [[ ! "$content" =~ (root=|PARTUUID=) ]]; then
    echo "validate: $f missing root= or PARTUUID= — possible corruption." >&2
    return 1
  fi
  if grep -q 'modules-load=dwc2,g_ether' <<<"$content"; then
    local n
    n=$(grep -o 'modules-load=dwc2,g_ether' <<<"$content" | wc -l | tr -d ' ')
    if [[ "${n:-0}" -gt 1 ]]; then
      echo "validate: duplicate modules-load=dwc2,g_ether in $f" >&2
      return 1
    fi
  fi
  if [[ "${#content}" -gt 4096 ]]; then
    echo "validate: $f line unreasonably long (${#content} chars)" >&2
    return 1
  fi
  return 0
}

ragnar_validate_config_txt() {
  local f="$1"
  [[ -f "$f" ]] || { echo "validate: missing $f" >&2; return 1; }
  if ! grep -qE '^[[:space:]]*[^#[:space:]]' "$f" 2>/dev/null; then
    echo "validate: $f has no active settings (only comments?) — suspicious." >&2
    return 1
  fi
  return 0
}

ragnar_validate_boot_after_install() {
  local fw err=0
  fw="$(ragnar_boot_firmware_dir)"
  ragnar_validate_config_txt "$fw/config.txt" || err=1
  ragnar_validate_cmdline_file "$fw/cmdline.txt" || err=1
  if [[ -f /boot/config.txt ]] && [[ "$fw" == "/boot/firmware" ]]; then
    ragnar_validate_config_txt /boot/config.txt || err=1
  fi
  return "$err"
}
BOOT_VALIDATE_INC
fi

append_if_missing() {
  local line="$1"
  local file="$2"
  grep -qxF "$line" "$file" 2>/dev/null || echo "$line" >> "$file"
}

ensure_user() {
  if ! id -u "$USER_NAME" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" "$USER_NAME"
  fi
}

select_display() {
  echo
  echo "Select display type:"
  echo "1. epd2in13"
  echo "2. epd2in13_V2"
  echo "3. epd2in13_V3"
  echo "4. epd2in13_V4"
  echo "5. epd2in7_V2"
  echo "6. epd2in7"
  echo "7. epd2in9_V2"
  echo "8. epd3in7"
  echo "9. displayhatmini (320x240 IPS LCD)"
  echo "10. headless"
  echo
  read -p "Enter choice (1-10): " CHOICE
  case "$CHOICE" in
    1) DISPLAY_MODE="epd"; SELECTED_EPD="epd2in13"; RAGNAR_ENTRYPOINT="Ragnar.py" ;;
    2) DISPLAY_MODE="epd"; SELECTED_EPD="epd2in13_V2"; RAGNAR_ENTRYPOINT="Ragnar.py" ;;
    3) DISPLAY_MODE="epd"; SELECTED_EPD="epd2in13_V3"; RAGNAR_ENTRYPOINT="Ragnar.py" ;;
    4) DISPLAY_MODE="epd"; SELECTED_EPD="epd2in13_V4"; RAGNAR_ENTRYPOINT="Ragnar.py" ;;
    5) DISPLAY_MODE="epd"; SELECTED_EPD="epd2in7_V2"; RAGNAR_ENTRYPOINT="Ragnar.py" ;;
    6) DISPLAY_MODE="epd"; SELECTED_EPD="epd2in7"; RAGNAR_ENTRYPOINT="Ragnar.py" ;;
    7) DISPLAY_MODE="epd"; SELECTED_EPD="epd2in9_V2"; RAGNAR_ENTRYPOINT="Ragnar.py" ;;
    8) DISPLAY_MODE="epd"; SELECTED_EPD="epd3in7"; RAGNAR_ENTRYPOINT="Ragnar.py" ;;
    9) DISPLAY_MODE="displayhatmini"; SELECTED_EPD="displayhatmini"; RAGNAR_ENTRYPOINT="Ragnar.py" ;;
    10) DISPLAY_MODE="headless"; SELECTED_EPD="epd2in13_V4"; RAGNAR_ENTRYPOINT="headlessRagnar.py" ;;
    *) echo "Invalid choice"; select_display ;;
  esac
  # Display HAT Mini: ask orientation (landscape vs portrait)
  if [ "$DISPLAY_MODE" = "displayhatmini" ]; then
    echo
    echo "Display HAT Mini orientation:"
    echo "  1. Landscape (320x240, default)"
    echo "  2. Portrait (240x320, vertical)"
    read -p "Enter choice (1 or 2) [1]: " ORIENT_CHOICE
    case "${ORIENT_CHOICE:-1}" in
      2) DISPLAYHATMINI_ROTATION=90; DISPLAYHATMINI_REF_W=240; DISPLAYHATMINI_REF_H=320 ;;
      *) DISPLAYHATMINI_ROTATION=180; DISPLAYHATMINI_REF_W=320; DISPLAYHATMINI_REF_H=240 ;;
    esac
  fi
}

ask_optional_features() {
  echo
  read -p "Install Pwnagotchi bridge? (y/N): " INSTALL_PWN
  read -p "Install PiSugar battery support? (y/N): " INSTALL_PISUGAR
}

# USB gadget Ethernet (SSH over USB to PC): requires dwc2 + g_ether; interface usb0.
# Refuses to edit cmdline if it is not a single non-empty line (multi-line cmdline bricks Pi boot).
ensure_usb_gadget_boot_config() {
  echo ""
  echo "========================================"
  echo " USB Ethernet gadget (dwc2 + g_ether)"
  echo "========================================"
  local cl="$CMDLINE_TXT"
  [ -f "$cl" ] || cl="/boot/cmdline.txt"
  ragnar_boot_backup 2>/dev/null || true
  append_if_missing "dtoverlay=dwc2" "$CONFIG_TXT"
  [ -f /boot/config.txt ] && [ "$CONFIG_TXT" != "/boot/config.txt" ] && append_if_missing "dtoverlay=dwc2" "/boot/config.txt" || true
  if [ -f "$cl" ]; then
    local line_count
    line_count=$(grep -cve '^[[:space:]]*$' "$cl" 2>/dev/null || echo 0)
    if [ "$line_count" -ne 1 ]; then
      echo "ERROR: $cl must be exactly one non-empty line for Raspberry Pi boot (found $line_count)."
      echo "       Refusing USB gadget cmdline edit. Fix cmdline manually or restore from ${cl}.ragnar.bak"
      return 1
    fi
    if ! tr -d '\n' <"$cl" | grep -q 'modules-load=dwc2,g_ether'; then
      cp "$cl" "${cl}.backup.$(date +%Y%m%d_%H%M%S)"
      # Single-line cmdline: append kernel module load for USB Ethernet gadget
      sed -i "s/\$/ modules-load=dwc2,g_ether/" "$cl"
      echo "✓ Appended modules-load=dwc2,g_ether to $cl"
    else
      echo "✓ $cl already contains modules-load=dwc2,g_ether"
    fi
    if command -v ragnar_validate_cmdline_file >/dev/null 2>&1; then
      ragnar_validate_cmdline_file "$cl" || {
        echo "ERROR: cmdline validation failed after USB gadget edit — restoring backup if present."
        if [ -f "${cl}.ragnar.bak" ]; then
          cp -a "${cl}.ragnar.bak" "$cl"
          echo "Restored $cl from ${cl}.ragnar.bak"
        fi
        return 1
      }
    fi
  else
    echo "WARNING: cmdline.txt not found ($CMDLINE_TXT or /boot/cmdline.txt). USB gadget may not load."
  fi
  echo "Use the Pi's USB DATA port with a data-capable cable. Reboot required before usb0 appears."
}

configure_static_ip() {
  echo
  echo "========================================"
  echo " Static IP Configuration"
  echo "========================================"
  echo
  echo "Choose which interface gets the static address."
  echo "  (Previously the installer only targeted the default route — often wlan0 — so a USB static IP"
  echo "   was wrongly applied to Wi-Fi. USB gadget needs usb0 + dwc2 + g_ether.)"
  echo
  read -p "Configure static IP? (y/N): " CONFIGURE_STATIC_IP

  if [[ ! "$CONFIGURE_STATIC_IP" =~ ^[Yy]$ ]]; then
    echo "Skipping static IP configuration."
    return 0
  fi

  echo ""
  echo "Tip: at each prompt, press Enter to accept the value in [brackets]."

  echo ""
  echo "Which interface should receive the static IPv4 address?"
  echo "  1) wlan0 — Wi-Fi"
  echo "  2) eth0 — Ethernet"
  echo "  3) usb0 — USB Ethernet gadget (SSH from PC over USB; Pi Zero / OTG)"
  read -p "Enter choice (1-3) [1]: " IF_CHOICE
  case "${IF_CHOICE:-1}" in
    2) ACTIVE_INTERFACE="eth0" ;;
    3) ACTIVE_INTERFACE="usb0" ;;
    *) ACTIVE_INTERFACE="wlan0" ;;
  esac

  if [ "$ACTIVE_INTERFACE" = "usb0" ]; then
    ensure_usb_gadget_boot_config
    echo ""
    echo "USB gadget: use a dedicated subnet (e.g. 192.168.7.x) different from your home LAN."
    echo "Example: Pi usb0 = 192.168.7.2, set the PC's RNDIS/USB Ethernet adapter to 192.168.7.1/24."
    read -p "Static IPv4 for usb0 [192.168.7.2]: " STATIC_IP
    STATIC_IP="${STATIC_IP:-192.168.7.2}"
    read -p "Gateway for usb0 [192.168.7.1] (type 'none' for no gateway): " STATIC_GATEWAY
    if [[ -z "${STATIC_GATEWAY// }" ]]; then
      STATIC_GATEWAY="192.168.7.1"
    elif [[ "$STATIC_GATEWAY" =~ ^(none|NONE|-)$ ]]; then
      STATIC_GATEWAY=""
    fi
    read -p "DNS for usb0 [8.8.8.8]: " STATIC_DNS
    STATIC_DNS="${STATIC_DNS:-8.8.8.8}"
  else
    # wlan0 / eth0: detect or ask (Enter = defaults derived from LAN or 192.168.1.x)
    echo ""
    echo "Selected interface: $ACTIVE_INTERFACE"
    CURRENT_IP=$(ip addr show "$ACTIVE_INTERFACE" 2>/dev/null | grep "inet " | awk '{print $2}' | cut -d/ -f1)
    CURRENT_GATEWAY=$(ip route | grep default | awk '{print $3}' | head -1)
    DEF_GW="${CURRENT_GATEWAY:-192.168.1.1}"
    DEF_SUB=$(echo "$DEF_GW" | cut -d. -f1-3)
    DEF_IP="${DEF_SUB}.100"
    if [ -n "$CURRENT_IP" ]; then
      echo "Current IP on $ACTIVE_INTERFACE: $CURRENT_IP"
      echo "Current default gateway: ${CURRENT_GATEWAY:-unknown}"
      echo
      read -p "Use current IP as static IP? (Y/n): " USE_CURRENT
      if [[ ! "$USE_CURRENT" =~ ^[Nn]$ ]]; then
        STATIC_IP="$CURRENT_IP"
        STATIC_GATEWAY="${CURRENT_GATEWAY:-}"
      else
        read -p "Static IPv4 for $ACTIVE_INTERFACE [$DEF_IP]: " STATIC_IP
        STATIC_IP="${STATIC_IP:-$DEF_IP}"
        read -p "Gateway [$DEF_GW] (type 'none' for no gateway): " STATIC_GATEWAY
        if [[ -z "${STATIC_GATEWAY// }" ]]; then
          STATIC_GATEWAY="$DEF_GW"
        elif [[ "$STATIC_GATEWAY" =~ ^(none|NONE|-)$ ]]; then
          STATIC_GATEWAY=""
        fi
      fi
    else
      read -p "Static IPv4 for $ACTIVE_INTERFACE [$DEF_IP]: " STATIC_IP
      STATIC_IP="${STATIC_IP:-$DEF_IP}"
      read -p "Gateway [$DEF_GW] (type 'none' for no gateway): " STATIC_GATEWAY
      if [[ -z "${STATIC_GATEWAY// }" ]]; then
        STATIC_GATEWAY="$DEF_GW"
      elif [[ "$STATIC_GATEWAY" =~ ^(none|NONE|-)$ ]]; then
        STATIC_GATEWAY=""
      fi
    fi
    read -p "DNS servers [8.8.8.8 1.1.1.1]: " STATIC_DNS
    STATIC_DNS="${STATIC_DNS:-8.8.8.8 1.1.1.1}"
  fi

  if [[ ! "$STATIC_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "ERROR: Invalid IP address format. Skipping static IP configuration."
    return 1
  fi

  if [ -n "$STATIC_GATEWAY" ] && [[ ! "$STATIC_GATEWAY" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "ERROR: Invalid gateway format. Skipping static IP configuration."
    return 1
  fi

  STATIC_IP_WITH_MASK="${STATIC_IP}/24"
  SUBNET=$(echo "$STATIC_IP" | cut -d. -f1-3)

  echo
  echo "Configuration summary:"
  echo "  Interface: $ACTIVE_INTERFACE"
  echo "  IP Address: $STATIC_IP_WITH_MASK"
  echo "  Gateway: ${STATIC_GATEWAY:-(none)}"
  echo "  DNS: $STATIC_DNS"
  echo
  read -p "Apply this configuration? (Y/n): " CONFIRM

  if [[ "$CONFIRM" =~ ^[Nn]$ ]]; then
    echo "Skipping static IP configuration."
    return 0
  fi

  DNS_COMMA=$(echo "$STATIC_DNS" | tr ' ' ',')

  # --- usb0: dedicated NM profile (device may not exist until after reboot) ---
  if [ "$ACTIVE_INTERFACE" = "usb0" ]; then
    if command -v nmcli >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager 2>/dev/null; then
      nmcli connection delete ragnar-usb-gadget 2>/dev/null || true
      if nmcli connection add type ethernet con-name ragnar-usb-gadget ifname usb0 \
        ipv4.method manual \
        ipv4.addresses "${STATIC_IP}/24" \
        ipv6.method ignore \
        connection.autoconnect yes 2>/dev/null; then
        echo "✓ NetworkManager profile ragnar-usb-gadget created for usb0"
        if [ -n "$STATIC_GATEWAY" ]; then
          nmcli connection modify ragnar-usb-gadget ipv4.gateway "$STATIC_GATEWAY" ipv4.dns "$DNS_COMMA" ipv4.ignore-auto-dns yes 2>/dev/null || true
        else
          nmcli connection modify ragnar-usb-gadget ipv4.never-default yes ipv4.ignore-auto-dns yes 2>/dev/null || true
        fi
        nmcli connection up ragnar-usb-gadget 2>/dev/null || echo "⚠ usb0 not present yet — profile will apply after reboot when the gadget loads."
      else
        echo "WARNING: nmcli could not create usb0 profile; try dhcpcd fallback."
      fi
    fi
    DHCPCD_CONF="/etc/dhcpcd.conf"
    if [ -f "$DHCPCD_CONF" ] && ! systemctl is-active --quiet NetworkManager 2>/dev/null; then
      cp "$DHCPCD_CONF" "${DHCPCD_CONF}.backup.$(date +%Y%m%d_%H%M%S)"
      sed -i "/^interface usb0$/,/^$/d" "$DHCPCD_CONF"
      {
        echo ""
        echo "# Ragnar installer: usb0 static"
        echo "interface usb0"
        echo "static ip_address=$STATIC_IP_WITH_MASK"
        [ -n "$STATIC_GATEWAY" ] && echo "static routers=$STATIC_GATEWAY"
        echo "static domain_name_servers=$STATIC_DNS"
      } >>"$DHCPCD_CONF"
      echo "✓ dhcpcd: usb0 block appended"
    fi
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "NOTE: 192.168.7.x applies only to **usb0** (USB gadget Ethernet)."
    echo "Wi-Fi (wlan0) can still have a **different** address from your router"
    echo "(e.g. 192.168.50.119). That is normal. Check each interface:"
    echo "  ip -br a"
    echo "Use ssh ragnar@$STATIC_IP only when connected over USB with usb0 up."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "SSH over USB: after reboot, set your PC's USB Ethernet/RNDIS to the same subnet (e.g. ${SUBNET}.1/24)."
    echo "Then: ssh ragnar@$STATIC_IP"
    echo "Run: sudo /home/ragnar/Ragnar/scripts/check_usb_ssh.sh"
    return 0
  fi

  # --- wlan0 / eth0: existing NM + dhcpcd path ---
  NM_CONN=""
  if command -v nmcli >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager 2>/dev/null; then
    NM_CONN=$(nmcli -t -f NAME,DEVICE connection show --active 2>/dev/null | awk -F: -v d="$ACTIVE_INTERFACE" '$2==d {print $1; exit}')
    if [ -z "$NM_CONN" ]; then
      NM_CONN=$(nmcli -t -f NAME,DEVICE connection show 2>/dev/null | awk -F: -v d="$ACTIVE_INTERFACE" '$2==d {print $1; exit}')
    fi
  fi

  if [ -n "$NM_CONN" ]; then
    echo ""
    echo "Using NetworkManager — applying static IP via nmcli."
    echo "Connection: $NM_CONN  Device: $ACTIVE_INTERFACE"
    if [ -z "$STATIC_GATEWAY" ]; then
      echo "WARNING: No gateway set; filling from default route or enter manually later."
      STATIC_GATEWAY=$(ip route | grep default | awk '{print $3}' | head -1)
    fi
    if nmcli connection modify "$NM_CONN" \
      ipv4.method manual \
      ipv4.addresses "${STATIC_IP}/24" \
      ipv4.gateway "$STATIC_GATEWAY" \
      ipv4.dns "$DNS_COMMA" \
      ipv4.ignore-auto-dns yes 2>/dev/null; then
      echo "✓ nmcli: static IPv4 set on \"$NM_CONN\""
    else
      echo "WARNING: nmcli modify failed; falling back to dhcpcd.conf"
      NM_CONN=""
    fi
    if [ -n "$NM_CONN" ]; then
      nmcli connection up "$NM_CONN" 2>/dev/null || true
      sleep 2
      NEW_IP=$(ip -4 -br addr show "$ACTIVE_INTERFACE" 2>/dev/null | awk '{print $3}' | cut -d/ -f1)
      if [ "$NEW_IP" = "$STATIC_IP" ]; then
        echo "✓ Address active on $ACTIVE_INTERFACE: $NEW_IP"
      else
        echo "⚠ Current IPv4 on $ACTIVE_INTERFACE: ${NEW_IP:-unknown} (expected $STATIC_IP) — reboot if needed."
      fi
      echo ""
      echo "After reboot: ssh ragnar@$STATIC_IP"
      return 0
    fi
  else
    if systemctl is-active --quiet NetworkManager 2>/dev/null; then
      echo ""
      echo "WARNING: NetworkManager active but no connection found for $ACTIVE_INTERFACE."
      echo "Falling back to dhcpcd.conf (may NOT apply on Bookworm)."
    fi
  fi

  DHCPCD_CONF="/etc/dhcpcd.conf"
  if [ ! -f "$DHCPCD_CONF" ]; then
    echo "WARNING: $DHCPCD_CONF not found. Static IP may not persist."
  fi

  if [ -f "$DHCPCD_CONF" ]; then
    cp "$DHCPCD_CONF" "${DHCPCD_CONF}.backup.$(date +%Y%m%d_%H%M%S)"
    sed -i "/^interface $ACTIVE_INTERFACE$/,/^$/d" "$DHCPCD_CONF"
    {
      echo ""
      echo "# Static IP configuration for $ACTIVE_INTERFACE (configured by Ragnar installer)"
      echo "interface $ACTIVE_INTERFACE"
      echo "static ip_address=$STATIC_IP_WITH_MASK"
      [ -n "$STATIC_GATEWAY" ] && echo "static routers=$STATIC_GATEWAY"
      echo "static domain_name_servers=$STATIC_DNS"
    } >>"$DHCPCD_CONF"
    echo "Static IP configuration added to $DHCPCD_CONF"
  fi

  echo ""
  echo "NOTE: dhcpcd fallback may require a reboot on Pi OS."
  echo "After reboot: ssh ragnar@$STATIC_IP"

  read -p "Apply static IP now (restart dhcpcd)? (y/N): " APPLY_NOW
  if [[ "$APPLY_NOW" =~ ^[Yy]$ ]]; then
    systemctl restart dhcpcd 2>/dev/null || systemctl restart networking 2>/dev/null || true
    sleep 3
    NEW_IP=$(ip addr show "$ACTIVE_INTERFACE" 2>/dev/null | grep "inet " | awk '{print $2}' | cut -d/ -f1)
    if [ "$NEW_IP" = "$STATIC_IP" ]; then
      echo "✓ Static IP applied successfully: $NEW_IP"
    else
      echo "⚠ Current IP: ${NEW_IP:-none} — reboot may be required."
    fi
  fi
}

patch_display_config() {
python3 - <<PY
from pathlib import Path
import json, re

base = Path("$RAGNAR_DIR")
shared_py = base / "shared.py"
epd_helper_py = base / "epd_helper.py"
config_json = base / "config" / "shared_config.json"

epd = "$SELECTED_EPD"
mode = "$DISPLAY_MODE"
# Display HAT Mini orientation (set by select_display)
dh_ref_w = "$DISPLAYHATMINI_REF_W"
dh_ref_h = "$DISPLAYHATMINI_REF_H"

if mode == "displayhatmini":
    width = int(dh_ref_w) if dh_ref_w and dh_ref_w.isdigit() else 320
    height = int(dh_ref_h) if dh_ref_h and dh_ref_h.isdigit() else 240
elif mode == "headless":
    width, height = 122, 250
else:
    dims = {
        "epd2in13": (122, 250),
        "epd2in13_V2": (122, 250),
        "epd2in13_V3": (122, 250),
        "epd2in13_V4": (122, 250),
        "epd2in7_V2": (176, 264),
        "epd2in7": (176, 264),
        "epd2in9_V2": (128, 296),
        "epd3in7": (280, 480),
    }
    width, height = dims.get(epd, (122, 250))

# Patch shared.py - Add displayhatmini to DISPLAY_PROFILES
if shared_py.exists():
    text = shared_py.read_text()
    
    # Update epd_type in get_default_config
    text = re.sub(r'"epd_type"\s*:\s*"[^"]+"', f'"epd_type": "{epd}"', text, count=1)
    text = re.sub(r'"ref_width"\s*:\s*\d+', f'"ref_width": {width}', text, count=1)
    text = re.sub(r'"ref_height"\s*:\s*\d+', f'"ref_height": {height}', text, count=1)
    
    if mode == "displayhatmini":
        # Add or update displayhatmini in DISPLAY_PROFILES with chosen orientation (portrait 240x320 or landscape 320x240)
        dhat_entry = f'"displayhatmini": {{"ref_width": {width}, "ref_height": {height}, "default_flip": False}}'
        if '"displayhatmini"' in text:
            # Update existing entry to current width/height (portrait vs landscape)
            text = re.sub(
                r'"displayhatmini"\s*:\s*\{\s*"ref_width"\s*:\s*\d+\s*,\s*"ref_height"\s*:\s*\d+[^}]*\}',
                dhat_entry,
                text,
                count=1
            )
        else:
            # Add displayhatmini after epd2in13_V4
            if '"epd2in13_V4"' in text:
                text = re.sub(
                    r'("epd2in13_V4"\s*:\s*\{[^}]+\},?)',
                    r'\1\n    ' + dhat_entry + ',',
                    text,
                    count=1
                )
            elif 'DISPLAY_PROFILES = {' in text:
                text = re.sub(
                    r'(DISPLAY_PROFILES\s*=\s*\{[^\}]*)(\})',
                    r'\1    ' + dhat_entry + r',\n\2',
                    text,
                    count=1
                )
    
    shared_py.write_text(text)
    print(f"✓ Patched shared.py - added displayhatmini to DISPLAY_PROFILES")
    
    # displayhatmini getbuffer() returns PIL Image, not bytes — skip e-ink buffer validation
    if mode == "displayhatmini":
        old_val = """            # Validate the driver works by doing a test getbuffer with a blank image
            try:
                test_img = Image.new('1', (self.width, self.height), 255)
                test_buf = self.epd_helper.epd.getbuffer(test_img)
                expected_size = int(self.width / 8) * self.height
                if len(test_buf) < expected_size:
                    raise ValueError(f"Buffer size mismatch: got {len(test_buf)}, expected {expected_size}")
            except Exception as ve:
                logger.warning(f"EPD driver '{epd_type}' buffer validation failed: {ve}, trying auto-detect...")
                raise  # Fall through to the auto-detect fallback below"""
        new_val = """            # Validate the driver works by doing a test getbuffer with a blank image
            # Skip for displayhatmini (LCD): getbuffer returns PIL Image, not bytes
            if epd_type != "displayhatmini":
                try:
                    test_img = Image.new('1', (self.width, self.height), 255)
                    test_buf = self.epd_helper.epd.getbuffer(test_img)
                    expected_size = int(self.width / 8) * self.height
                    if len(test_buf) < expected_size:
                        raise ValueError(f"Buffer size mismatch: got {len(test_buf)}, expected {expected_size}")
                except Exception as ve:
                    logger.warning(f"EPD driver '{epd_type}' buffer validation failed: {ve}, trying auto-detect...")
                    raise  # Fall through to the auto-detect fallback below"""
        if old_val in text and new_val not in text:
            text = text.replace(old_val, new_val)
            shared_py.write_text(text)
            print("✓ Patched shared.py: skip buffer validation for displayhatmini (LCD returns PIL Image)")

# Patch epd_helper.py - Add displayhatmini support
if epd_helper_py.exists() and mode == "displayhatmini":
    text = epd_helper_py.read_text()
    
    # Add displayhatmini to KNOWN_EPD_TYPES
    if '"displayhatmini"' not in text and "'displayhatmini'" not in text:
        # Find KNOWN_EPD_TYPES list and add displayhatmini
        text = re.sub(
            r'(KNOWN_EPD_TYPES\s*=\s*\[[^\]]*"epd3in7",)',
            r'\1\n    "displayhatmini",',
            text
        )
    
    # Patch _load_epd_module to handle displayhatmini import path
    # displayhatmini is in waveshare_epd, not resources.waveshare_epd
    if 'if self.epd_type == "displayhatmini":' not in text:
        # Insert special handling at the start of _load_epd_module
        text = text.replace(
            '    def _load_epd_module(self):\n        try:\n            epd_module_name = f\'resources.waveshare_epd.{self.epd_type}\'',
            '''    def _load_epd_module(self):
        # Special handling for displayhatmini (installed via pip, not in resources/)
        if self.epd_type == "displayhatmini":
            try:
                from waveshare_epd import displayhatmini
                return displayhatmini.EPD()
            except ImportError as e:
                logger.error(f"Display HAT Mini module not found: {e}")
                raise
        try:
            epd_module_name = f'resources.waveshare_epd.{self.epd_type}\''''
        )
    
    epd_helper_py.write_text(text)
    print(f"✓ Patched epd_helper.py - added displayhatmini support")

# Update config JSON
if config_json.exists():
    cfg = json.loads(config_json.read_text())
else:
    cfg = {}

cfg["epd_type"] = epd
cfg["ref_width"] = width
cfg["ref_height"] = height

if mode == "displayhatmini":
    cfg["screen_delay"] = 0.03
    cfg["image_display_delaymin"] = 0.03
    cfg["image_display_delaymax"] = 0.06

config_json.parent.mkdir(parents=True, exist_ok=True)
config_json.write_text(json.dumps(cfg, indent=4))
print(f"✓ Updated config JSON: epd_type={epd}, ref_width={width}, ref_height={height}")
PY
}

install_pisugar_support() {
  if [[ ! "$INSTALL_PISUGAR" =~ ^[Yy]$ ]]; then
    return 0
  fi
  echo "========================================"
  echo " PiSugar power manager (PiSugar 3 — vendor release channel)"
  echo "========================================"
  # Official flow: https://github.com/PiSugar/PiSugar/wiki/PiSugar-3-Series#software-installation
  #   wget https://cdn.pisugar.com/release/pisugar-power-manager.sh
  #   bash pisugar-power-manager.sh -c release
  # Do NOT use: curl ... | bash — that feeds the script on stdin, so whiptail/dialog
  # cannot read keyboard input. Run from a file so stdin stays the terminal (ssh -t).
  PISUGAR_URL="https://cdn.pisugar.com/release/pisugar-power-manager.sh"
  PISUGAR_TMP="$(mktemp /tmp/pisugar-power-manager-XXXXXX.sh)"
  if ! curl -sSL -f "$PISUGAR_URL" -o "$PISUGAR_TMP"; then
    echo "WARNING: Could not download PiSugar installer."
    rm -f "$PISUGAR_TMP"
    return 1
  fi
  chmod +x "$PISUGAR_TMP"
  if [ -t 0 ]; then
    echo "Using vendor -c release channel (see PiSugar 3 wiki). Model prompts may still appear."
    echo "(If prompts fail, use: ssh -t ... so SSH allocates a terminal.)"
    unset DEBIAN_FRONTEND
  else
    echo "WARNING: No TTY on stdin — if install fails, use ssh -t or a local console, then:"
    echo "  curl -sSL $PISUGAR_URL -o /tmp/p.sh && sudo bash /tmp/p.sh -c release"
    export DEBIAN_FRONTEND=noninteractive
  fi
  if bash "$PISUGAR_TMP" -c release; then
    echo "PiSugar installer finished."
    echo "PiSugar 3 OTA firmware (optional, with hardware attached):"
    echo "  curl -sSL https://cdn.pisugar.com/release/PiSugarUpdate.sh | sudo bash"
    if [ ! -t 0 ]; then
      echo "If hardware is attached, run: sudo dpkg-reconfigure pisugar-server"
    fi
    systemctl enable pisugar-server 2>/dev/null || true
    systemctl start pisugar-server 2>/dev/null || true
    chmod +x "$RAGNAR_DIR/scripts/install_pisugar_boot_dropin.sh" 2>/dev/null || true
    if [[ -x "$RAGNAR_DIR/scripts/install_pisugar_boot_dropin.sh" ]]; then
      echo "Applying PiSugar boot ordering (I2C / udev)..."
      "$RAGNAR_DIR/scripts/install_pisugar_boot_dropin.sh" || echo "WARNING: install_pisugar_boot_dropin.sh reported an error (check logs)."
    elif [[ -x "$INSTALLER_DIR/Ragnar/scripts/install_pisugar_boot_dropin.sh" ]]; then
      chmod +x "$INSTALLER_DIR/Ragnar/scripts/install_pisugar_boot_dropin.sh" 2>/dev/null || true
      "$INSTALLER_DIR/Ragnar/scripts/install_pisugar_boot_dropin.sh" || echo "WARNING: install_pisugar_boot_dropin.sh reported an error."
    fi
  else
    echo "WARNING: PiSugar install failed or was cancelled. Run manually (PiSugar 3 wiki):"
    echo "  curl -sSL https://cdn.pisugar.com/release/pisugar-power-manager.sh -o /tmp/p.sh && sudo bash /tmp/p.sh -c release"
  fi
  rm -f "$PISUGAR_TMP"
}

install_pwnagotchi_bridge() {
  if [[ ! "$INSTALL_PWN" =~ ^[Yy]$ ]]; then
    return 0
  fi
  if [ ! -x "$RAGNAR_DIR/scripts/install_pwnagotchi.sh" ]; then
    echo "WARNING: Pwnagotchi bridge installer not found."
    return 0
  fi
  echo "Preparing config for Pwnagotchi bridge..."
  patch_display_config
  echo "Installing Pwnagotchi bridge..."
  (cd "$RAGNAR_DIR" && ./scripts/install_pwnagotchi.sh) || echo "WARNING: Pwnagotchi bridge installer reported an error"
}

# Built-in diagnostic and auto-fix functions
diagnose_and_fix_service() {
  echo ""
  echo "========================================"
  echo " Diagnosing Ragnar Service"
  echo "========================================"
  
  local issues_found=0
  local fixes_applied=0
  
  # Check if Ragnar directory exists
  if [ ! -d "$RAGNAR_DIR" ]; then
    echo "✗ Ragnar directory not found: $RAGNAR_DIR"
    issues_found=$((issues_found + 1))
    return 1
  fi
  
  # Check if Ragnar.py exists
  if [ ! -f "$RAGNAR_DIR/$RAGNAR_ENTRYPOINT" ]; then
    echo "✗ Entrypoint not found: $RAGNAR_DIR/$RAGNAR_ENTRYPOINT"
    issues_found=$((issues_found + 1))
    return 1
  fi
  
  # Check Python imports
  echo "Checking Python dependencies..."
  python3 <<'PYDIAG'
import sys
sys.path.insert(0, '/home/ragnar/Ragnar')

missing = []
try:
    import shared
    print("  ✓ shared")
except Exception as e:
    print(f"  ✗ shared: {e}")
    missing.append("shared")

try:
    from PIL import Image
    print("  ✓ PIL/Pillow")
except ImportError:
    print("  ✗ PIL/Pillow - MISSING")
    missing.append("pillow")

try:
    import numpy
    print("  ✓ numpy")
except ImportError:
    print("  ✗ numpy - MISSING")
    missing.append("numpy")

try:
    import pandas
    print("  ✓ pandas")
except ImportError:
    print("  ✗ pandas - MISSING")
    missing.append("pandas")

try:
    import paramiko
    print("  ✓ paramiko")
except ImportError:
    print("  ✗ paramiko - MISSING")
    missing.append("paramiko")

if missing:
    print(f"\n  Missing packages: {', '.join(missing)}")
    sys.exit(1)
PYDIAG
  
  if [ $? -ne 0 ]; then
    echo "⚠ Missing Python packages detected. Installing..."
    cd "$RAGNAR_DIR"
    # Fix package version constraints
    if [ -f requirements.txt ]; then
      sed -i 's/pisugar[<>=!].*/pisugar>=0.1.1/' requirements.txt 2>/dev/null || true
      sed -i 's/^pisugar$/pisugar>=0.1.1/' requirements.txt 2>/dev/null || true
      sed -i 's/spidev==3\.5/spidev>=3.6.0/' requirements.txt 2>/dev/null || true
      sed -i 's/cryptography.*/cryptography<45,>=41.0.5/' requirements.txt 2>/dev/null || true
    fi
    pip3 install --break-system-packages --no-cache-dir -r requirements.txt 2>&1 | grep -v "DEPRECATION:" 2>/dev/null || true
    pip3 install --break-system-packages --no-cache-dir pillow numpy pandas pandas-stubs "Flask-SQLAlchemy>=3.0.1" paramiko st7789 2>/dev/null || true
    fixes_applied=$((fixes_applied + 1))
  fi
  
  # Check display driver (if displayhatmini)
  if [ "$DISPLAY_MODE" = "displayhatmini" ]; then
    echo "Checking display driver..."
    python3 <<'PYDIAG'
import sys
try:
    from waveshare_epd import displayhatmini
    print("  ✓ displayhatmini module found")
    
    # Test initialization
    try:
        epd = displayhatmini.EPD()
        result = epd.init()
        if result == 0:
            print("  ✓ Display initialization successful")
        else:
            print(f"  ✗ Display init returned: {result}")
            sys.exit(1)
    except Exception as e:
        print(f"  ✗ Display init failed: {e}")
        sys.exit(1)
except ImportError as e:
    print(f"  ✗ displayhatmini not found: {e}")
    sys.exit(1)
PYDIAG
    
    if [ $? -ne 0 ]; then
      echo "⚠ Display driver issue detected. Reinstalling..."
      cd "$HOME_DIR/e-Paper/RaspberryPi_JetsonNano/python"
      pip3 install --break-system-packages --force-reinstall . 2>/dev/null || true
      fixes_applied=$((fixes_applied + 1))
    fi
  fi
  
  # Check file permissions
  echo "Checking file permissions..."
  if [ ! -r "$RAGNAR_DIR/$RAGNAR_ENTRYPOINT" ]; then
    echo "⚠ Fixing file permissions..."
    chown -R root:root "$RAGNAR_DIR" 2>/dev/null || true
    chmod +x "$RAGNAR_DIR/$RAGNAR_ENTRYPOINT" 2>/dev/null || true
    fixes_applied=$((fixes_applied + 1))
  fi
  
  # Test Ragnar syntax
  echo "Checking Ragnar.py syntax..."
  if ! python3 -m py_compile "$RAGNAR_DIR/$RAGNAR_ENTRYPOINT" 2>/dev/null; then
    echo "✗ Syntax error in $RAGNAR_ENTRYPOINT"
    issues_found=$((issues_found + 1))
  else
    echo "  ✓ Syntax valid"
  fi
  
  # Check service file
  echo "Checking service configuration..."
  if [ ! -f /etc/systemd/system/ragnar.service ]; then
    echo "✗ Service file not found"
    issues_found=$((issues_found + 1))
  else
    echo "  ✓ Service file exists"
  fi
  
  echo ""
  if [ $issues_found -eq 0 ]; then
    echo "✓ All checks passed"
    if [ $fixes_applied -gt 0 ]; then
      echo "  (Applied $fixes_applied fix(es))"
    fi
    return 0
  else
    echo "✗ Found $issues_found issue(s)"
    return 1
  fi
}

show_network_info() {
  echo ""
  echo "========================================"
  echo " Network Information"
  echo "========================================"
  
  # Get current IP addresses
  CURRENT_IPS=$(hostname -I 2>/dev/null || ip addr show | grep "inet " | awk '{print $2}' | cut -d/ -f1)
  
  if [ -n "$CURRENT_IPS" ]; then
    echo "Current IP addresses:"
    for ip in $CURRENT_IPS; do
      echo "  - $ip"
    done
    echo ""
    echo "Connect via SSH:"
    FIRST_IP=$(echo $CURRENT_IPS | awk '{print $1}')
    echo "  ssh ragnar@$FIRST_IP"
    
    # Try mDNS
    if command -v avahi-resolve >/dev/null 2>&1; then
      MDNS_NAME=$(hostname).local
      echo "  ssh ragnar@$MDNS_NAME"
    fi
  else
    echo "⚠ No IP addresses found. Network may not be connected."
  fi
  
  # Show interface status
  echo ""
  echo "Network interfaces:"
  ip link show | grep -E "^[0-9]+:" | awk '{print "  " $2 " - " $9}' | sed 's/:$//'
  
  echo ""
}

auto_fix_service_errors() {
  local max_attempts=3
  local attempt=1
  
  while [ $attempt -le $max_attempts ]; do
    echo ""
    echo "Attempt $attempt/$max_attempts: Starting Ragnar service..."
    
    if systemctl start ragnar 2>/dev/null; then
      sleep 3
      if systemctl is-active --quiet ragnar; then
        echo "✓ Service started successfully"
        return 0
      fi
    fi
    
    # Get the error
    local error_log=$(journalctl -u ragnar -n 5 --no-pager 2>/dev/null | tail -1)
    
    # Try to auto-fix common issues
    if echo "$error_log" | grep -qi "ModuleNotFoundError\|ImportError"; then
      echo "⚠ Import error detected. Installing missing packages..."
      cd "$RAGNAR_DIR"
      # Fix pisugar version if needed (only version 0.1.1 exists)
    if [ -f requirements.txt ] && grep -q "pisugar" requirements.txt; then
      sed -i 's/pisugar[<>=!].*/pisugar>=0.1.1/' requirements.txt 2>/dev/null || \
      sed -i 's/^pisugar$/pisugar>=0.1.1/' requirements.txt 2>/dev/null || true
    fi
    pip3 install --break-system-packages --no-cache-dir -r requirements.txt 2>&1 | grep -v "DEPRECATION:" 2>/dev/null || true
      pip3 install --break-system-packages --no-cache-dir pillow numpy pandas pandas-stubs "Flask-SQLAlchemy>=3.0.1" paramiko st7789 2>/dev/null || true
    fi
    
    if echo "$error_log" | grep -qi "PermissionError\|Permission denied"; then
      echo "⚠ Permission error detected. Fixing permissions..."
      chown -R root:root "$RAGNAR_DIR" 2>/dev/null || true
      chmod +x "$RAGNAR_DIR/$RAGNAR_ENTRYPOINT" 2>/dev/null || true
    fi
    
    if echo "$error_log" | grep -qi "displayhatmini\|display.*not found"; then
      echo "⚠ Display driver issue. Reinstalling..."
      cd "$HOME_DIR/e-Paper/RaspberryPi_JetsonNano/python"
      pip3 install --break-system-packages --force-reinstall . 2>/dev/null || true
    fi
    
    attempt=$((attempt + 1))
    sleep 2
  done
  
  echo "✗ Failed to start service after $max_attempts attempts"
  echo ""
  echo "Recent error logs:"
  journalctl -u ragnar -n 20 --no-pager
  return 1
}

# Function to wait for apt lock and retry
wait_for_apt_lock() {
  local max_attempts=30
  local attempt=0
  
  while [ $attempt -lt $max_attempts ]; do
    if ! lsof /var/lib/apt/lists/lock >/dev/null 2>&1 && ! lsof /var/lib/dpkg/lock >/dev/null 2>&1; then
      return 0
    fi
    echo "Waiting for apt lock to be released... (attempt $((attempt + 1))/$max_attempts)"
    sleep 2
    attempt=$((attempt + 1))
  done
  
  echo "WARNING: Apt lock still held after $max_attempts attempts"
  echo "You may need to:"
  echo "  1. Wait for other package operations to complete"
  echo "  2. Or run: sudo killall packagekitd"
  echo "  3. Or run: sudo fuser -k /var/lib/apt/lists/lock"
  return 1
}

echo "Updating system..."
wait_for_apt_lock
if [ $? -ne 0 ]; then
  echo "ERROR: Could not acquire apt lock. Please try again in a few moments."
  echo "If the problem persists, run: sudo killall packagekitd && sudo fuser -k /var/lib/apt/lists/lock"
  exit 1
fi

apt update -y || {
  echo "WARNING: apt update failed, retrying in 5 seconds..."
  sleep 5
  wait_for_apt_lock
  apt update -y || {
    echo "ERROR: apt update failed after retry"
    exit 1
  }
}

apt upgrade -y || {
  echo "WARNING: apt upgrade failed, but continuing with installation..."
}

echo "Installing base packages..."
apt install -y git wget curl lsof sudo build-essential python3 python3-pip python3-dev python3-pil python3-numpy python3-pandas python3-spidev libjpeg-dev zlib1g-dev libpng-dev libffi-dev libssl-dev libgpiod-dev libcap-dev libi2c-dev libopenjp2-7 libopenblas-dev libblas-dev liblapack-dev nmap bluez bluez-tools bridge-utils network-manager i2c-tools rfkill || true

echo "Installing Python packages..."
  pip3 install --break-system-packages --ignore-installed --no-cache-dir typing_extensions paramiko st7789 luma.lcd luma.core spidev pillow numpy pandas pandas-stubs openai "cryptography<45" || true

echo "Enabling SPI and I2C..."
if command -v raspi-config >/dev/null 2>&1; then
  raspi-config nonint do_spi 0 || true
  raspi-config nonint do_i2c 0 || true
fi

echo "Ensuring SSH is enabled..."
systemctl enable ssh 2>/dev/null || systemctl enable sshd 2>/dev/null || true
systemctl start ssh 2>/dev/null || systemctl start sshd 2>/dev/null || true
# Also enable via raspi-config for Raspberry Pi OS
if command -v raspi-config >/dev/null 2>&1; then
  raspi-config nonint do_ssh 0 || true
fi
# Create SSH file for headless setup (Raspberry Pi OS)
touch /boot/ssh 2>/dev/null || touch /boot/firmware/ssh 2>/dev/null || true
echo "SSH enabled and started"

# Reachable on LAN / USB Ethernet: explicit listen (overrides accidental localhost-only main config)
if [ -d /etc/ssh/sshd_config.d ]; then
  _sshd_listen_dropin() {
    cat > /etc/ssh/sshd_config.d/50-ragnar-ssh-listenall.conf <<'SSHLISTEN'
# Ragnar installer: SSH on all interfaces (USB gadget + Wi-Fi + Ethernet)
SSHLISTEN
    printf '%s\n' "$1" >> /etc/ssh/sshd_config.d/50-ragnar-ssh-listenall.conf
  }
  if command -v sshd >/dev/null 2>&1; then
    _sshd_listen_dropin $'ListenAddress 0.0.0.0\nListenAddress ::'
    if ! sshd -t 2>/dev/null; then
      echo "NOTE: sshd -t failed with IPv6 ListenAddress — retrying IPv4 only."
      _sshd_listen_dropin 'ListenAddress 0.0.0.0'
    fi
    if sshd -t 2>/dev/null; then
      systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
      echo "✓ sshd drop-in applied (50-ragnar-ssh-listenall.conf); config validated"
    else
      echo "WARNING: sshd -t still failing — removing 50-ragnar-ssh-listenall.conf"
      rm -f /etc/ssh/sshd_config.d/50-ragnar-ssh-listenall.conf
    fi
  fi
fi
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi 'Status: active'; then
  ufw allow OpenSSH 2>/dev/null || ufw allow 22/tcp 2>/dev/null || true
  echo "✓ UFW: allowed OpenSSH (port 22)"
fi

echo "Applying boot-safe defaults (SPI + headless GPU split; backups + validation)..."
echo "  (Optional: RAGNAR_INSTALLER_PERF_TUNING=1 enables legacy core_freq tweaks — not recommended on Pi Zero 2 W.)"
ragnar_boot_backup
# Older installer runs: remove act LED override (restores normal blink / heartbeat on green ACT)
sed -i '/^[[:space:]]*dtparam=act_led_trigger=none/d' "$CONFIG_TXT" 2>/dev/null || true
[ -f /boot/config.txt ] && sed -i '/^[[:space:]]*dtparam=act_led_trigger=none/d' /boot/config.txt 2>/dev/null || true
append_if_missing "dtparam=spi=on" "$CONFIG_TXT"
append_if_missing "gpu_mem=128" "$CONFIG_TXT"
if [[ "${RAGNAR_INSTALLER_PERF_TUNING:-0}" == "1" ]]; then
  append_if_missing "core_freq=500" "$CONFIG_TXT"
  append_if_missing "core_freq_min=500" "$CONFIG_TXT"
  echo "  Applied RAGNAR_INSTALLER_PERF_TUNING=1 (core_freq / core_freq_min)."
fi
# Do NOT set act_led_trigger=none — it stops normal green ACT blinking and is often mistaken for a boot hang.
# Legacy installs: remove that line if you want the default heartbeat/activity behaviour back.
[ -f /boot/config.txt ] && append_if_missing "dtparam=spi=on" "/boot/config.txt" || true
[[ "${RAGNAR_INSTALLER_PERF_TUNING:-0}" == "1" ]] && { [ -f /boot/config.txt ] && append_if_missing "gpu_mem=128" "/boot/config.txt" || true; }

select_display
ask_optional_features
configure_static_ip

echo "Validating boot files after firmware/network changes..."
if ! ragnar_validate_boot_after_install; then
  echo ""
  echo "FATAL: Boot file validation failed. Restoring pre-install backups (*.ragnar.bak) and aborting."
  ragnar_boot_restore_from_bak
  echo "Installer stopped so the system stays bootable. Fix issues above or report a bug."
  exit 1
fi

echo "Preparing Ragnar directory..."
ensure_user
mkdir -p "$HOME_DIR"
chown -R "$USER_NAME:$USER_NAME" "$HOME_DIR"

cd "$HOME_DIR"
rm -rf "$RAGNAR_DIR" || true

if [ -d "$INSTALLER_DIR/Ragnar" ] && [ -f "$INSTALLER_DIR/Ragnar/Ragnar.py" ]; then
  echo "Copying Ragnar from installer directory..."
  cp -a "$INSTALLER_DIR/Ragnar" "$RAGNAR_DIR"
  # Single docs folder: copy repo/docs into deployed Ragnar so docs/ links work on the Pi
  if [ -d "$INSTALLER_DIR/docs" ]; then
    cp -a "$INSTALLER_DIR/docs" "$RAGNAR_DIR/docs"
    # Ragnar/README.md uses ../docs/ in repo; on Pi we have Ragnar/docs so use docs/
    [ -f "$RAGNAR_DIR/README.md" ] && sed -i 's|\.\./docs/|docs/|g' "$RAGNAR_DIR/README.md"
  fi
else
  echo "Cloning ragnar-displayhatmini repo (contains Ragnar app)..."
  CLONE_DIR="$HOME_DIR/ragnar-displayhatmini-clone"
  rm -rf "$CLONE_DIR"
  git clone --depth 1 https://github.com/DarkSecNetwork/ragnar-displayhatmini.git "$CLONE_DIR"
  if [ -d "$CLONE_DIR/Ragnar" ] && [ -f "$CLONE_DIR/Ragnar/Ragnar.py" ]; then
    cp -a "$CLONE_DIR/Ragnar" "$RAGNAR_DIR"
    [ -d "$CLONE_DIR/docs" ] && cp -a "$CLONE_DIR/docs" "$RAGNAR_DIR/docs"
    [ -f "$RAGNAR_DIR/README.md" ] && sed -i 's|\.\./docs/|docs/|g' "$RAGNAR_DIR/README.md"
  else
    echo "Falling back to upstream Ragnar..."
    git clone https://github.com/PierreGode/Ragnar.git "$RAGNAR_DIR"
  fi
  rm -rf "$CLONE_DIR"
fi
cd "$RAGNAR_DIR"

echo "Installing Waveshare display library..."
cd "$HOME_DIR"
if [ ! -d e-Paper ]; then
  git clone --depth=1 --filter=blob:none --sparse https://github.com/waveshareteam/e-Paper.git
  cd e-Paper
  git sparse-checkout set RaspberryPi_JetsonNano
else
  cd e-Paper
fi
cd RaspberryPi_JetsonNano/python
pip3 install --break-system-packages --ignore-installed . || true

cd "$RAGNAR_DIR"

echo "Installing Ragnar requirements..."
if [ -f requirements.txt ]; then
  echo "Fixing package version constraints..."
  # Fix pisugar version (only 0.1.1 exists)
  sed -i 's/pisugar[<>=!].*/pisugar>=0.1.1/' requirements.txt 2>/dev/null || true
  sed -i 's/^pisugar$/pisugar>=0.1.1/' requirements.txt 2>/dev/null || true
  # Fix spidev for st7789 compatibility
  sed -i 's/spidev==3\.5/spidev>=3.6.0/' requirements.txt 2>/dev/null || true
  # Fix cryptography for pyopenssl compatibility
  sed -i 's/cryptography.*/cryptography<45,>=41.0.5/' requirements.txt 2>/dev/null || true
  # libcap-dev (installed above) is required for python-prctl (Ragnar upstream requirement)
  # Install requirements, suppressing deprecation warnings
  pip3 install --break-system-packages --ignore-installed --no-cache-dir -r requirements.txt 2>&1 | grep -v "DEPRECATION:" || true
  # If python-prctl still failed (e.g. libcap not found), try without it so Ragnar can start
  if ! python3 -c "import prctl" 2>/dev/null; then
    echo "  python-prctl not available (optional); continuing..."
  fi
fi
# Install core packages (--no-cache-dir avoids invalid cached wheels e.g. paramiko-0.9_ivysaur from Pwnagotchi)
pip3 install --break-system-packages --ignore-installed --no-cache-dir paramiko st7789 luma.lcd luma.core pandas pandas-stubs "Flask-SQLAlchemy>=3.0.1" openai "cryptography<45" 2>&1 | grep -v "DEPRECATION:" || true

if [ "$DISPLAY_MODE" = "displayhatmini" ]; then
  echo "Installing Display HAT Mini dependencies (gpiod, gpiodevice, gpiozero, lgpio)..."
  apt install -y python3-gpiod python3-lgpio 2>/dev/null || true
  pip3 install --break-system-packages gpiod gpiodevice "gpiozero>=2.0" 2>&1 | grep -v "DEPRECATION:" || true
  echo "Creating Display HAT Mini compatibility driver..."
  WSPATH=$(python3 - <<'PY'
import importlib.util
spec = importlib.util.find_spec("waveshare_epd")
print(spec.submodule_search_locations[0] if spec else "")
PY
)
  if [ -z "$WSPATH" ] || [ ! -d "$WSPATH" ]; then
    echo "ERROR: waveshare_epd package path not found."
    exit 1
  fi
  DHAT_ROT="${DISPLAYHATMINI_ROTATION:-180}"
  # Physical panel is always 320x240. st7789 only allows rotation 0 or 180 (no 90/270 for non-square).
  # For portrait: init ST7789 at 320x240 (full panel), report logical 240x320 to Ragnar, rotate image in software so full screen is used.
  # For landscape: init 320x240 with rotation 180 (or 0); no image rotation.
  if [ "$DHAT_ROT" = "90" ]; then
    DHAT_LOGICAL_W=240; DHAT_LOGICAL_H=320; DHAT_ST7789_ROT=0; DHAT_PORTRAIT=1
  elif [ "$DHAT_ROT" = "270" ]; then
    DHAT_LOGICAL_W=240; DHAT_LOGICAL_H=320; DHAT_ST7789_ROT=180; DHAT_PORTRAIT=1
  elif [ "$DHAT_ROT" = "0" ]; then
    DHAT_LOGICAL_W=320; DHAT_LOGICAL_H=240; DHAT_ST7789_ROT=0; DHAT_PORTRAIT=0
  else
    DHAT_LOGICAL_W=320; DHAT_LOGICAL_H=240; DHAT_ST7789_ROT=180; DHAT_PORTRAIT=0
  fi
  cat > "$WSPATH/displayhatmini.py" <<PY
import sys
from PIL import Image

# Try to import st7789 library (correct import)
try:
    import st7789
    ST7789_AVAILABLE = True
except ImportError:
    try:
        # Fallback to ST7789 (uppercase) if lowercase doesn't work
        import ST7789 as st7789
        ST7789_AVAILABLE = True
    except ImportError:
        ST7789_AVAILABLE = False
        print("ERROR: st7789 library not found. Install with: pip3 install st7789", file=sys.stderr)

# Do NOT use RPi.GPIO here for backlight. Mixing RPi.GPIO with gpiozero (menu buttons A/B/X/Y)
# breaks GPIO on many setups (PiSugar stacked, Bookworm). The st7789 driver controls backlight=13.

class EPD:
    width = 320
    height = 240
    def __init__(self):
        self.disp = None

    def init(self):
        if not ST7789_AVAILABLE:
            print("ERROR: st7789 library not available", file=sys.stderr)
            return -1
        if self.disp is None:
            try:
                # Display HAT Mini: physical panel is always 320x240. Init ST7789 at full physical size so entire panel is used.
                # Portrait: we report 240x320 to Ragnar and rotate the image in software in display()/Clear().
                self._portrait = $DHAT_PORTRAIT
                self.disp = st7789.ST7789(
                    width=320,
                    height=240,
                    rotation=$DHAT_ST7789_ROT,
                    port=0,
                    cs=1,
                    dc=9,
                    rst=None,
                    backlight=13,
                    spi_speed_hz=60000000,
                    offset_left=0,
                    offset_top=0
                )
                self.disp.begin()
                self.width = $DHAT_LOGICAL_W
                self.height = $DHAT_LOGICAL_H
                print("Display HAT Mini initialized successfully", file=sys.stderr)
            except Exception as e:
                print(f"ERROR: Failed to initialize display: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc()
                return -1
        return 0
    
    def getbuffer(self, img):
        if img.mode != "RGB":
            img = img.convert("RGB")
        if img.size != (self.width, self.height):
            img = img.resize((self.width, self.height), Image.Resampling.LANCZOS)
        return img
    
    def display(self, img):
        if self.disp is None:
            if self.init() != 0:
                return
        try:
            buffer_img = self.getbuffer(img)
            if getattr(self, '_portrait', False):
                buffer_img = buffer_img.transpose(Image.ROTATE_270)
            self.disp.display(buffer_img)
        except Exception as e:
            print(f"ERROR: Display update failed: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
    
    def Clear(self, color=255):
        if self.disp is None:
            if self.init() != 0:
                return
        try:
            if isinstance(color, int):
                fill = (color, color, color) if color < 256 else (255, 255, 255)
            else:
                fill = color
            if getattr(self, '_portrait', False):
                fill_img = Image.new("RGB", (320, 240), fill)
            else:
                fill_img = Image.new("RGB", (self.width, self.height), fill)
            self.disp.display(fill_img)
        except Exception as e:
            print(f"ERROR: Clear failed: {e}", file=sys.stderr)
    
    def sleep(self):
        """Optional power save — avoid RPi.GPIO; st7789 may expose backlight API on some versions."""
        pass

    def module_exit(self):
        """Cleanup"""
        try:
            self.disp = None
        except Exception:
            pass
    
    def Dev_exit(self):
        """Cleanup"""
        self.module_exit()
PY
fi

echo "Patching Ragnar config..."
patch_display_config

echo "Creating data directories and dictionary files..."
mkdir -p "$RAGNAR_DIR/data/input/dictionary"
mkdir -p "$RAGNAR_DIR/data/logs" "$RAGNAR_DIR/data/output/crackedpwd" "$RAGNAR_DIR/data/output/data_stolen" "$RAGNAR_DIR/data/output/vulnerabilities" "$RAGNAR_DIR/data/output/scan_results" "$RAGNAR_DIR/data/output/zombies" 2>/dev/null || true
if [ ! -f "$RAGNAR_DIR/data/input/dictionary/users.txt" ]; then
  cat > "$RAGNAR_DIR/data/input/dictionary/users.txt" << 'DICT'
admin
root
user
administrator
test
guest
DICT
  echo "  Created data/input/dictionary/users.txt"
fi
if [ ! -f "$RAGNAR_DIR/data/input/dictionary/passwords.txt" ]; then
  cat > "$RAGNAR_DIR/data/input/dictionary/passwords.txt" << 'DICT'
password
123456
admin
root
password123
123
test
guest
DICT
  echo "  Created data/input/dictionary/passwords.txt"
fi
# Ensure network scanner is in actions.json so orchestrator can start (upstream may omit it)
ACTIONS_JSON="$RAGNAR_DIR/config/actions.json"
if [ -f "$ACTIONS_JSON" ]; then
  python3 <<PY
import json
path = "$ACTIONS_JSON"
with open(path, "r") as f:
    actions = json.load(f)
has_scanning = any(a.get("b_module") == "scanning" for a in actions)
if not has_scanning:
    scanning_entry = {"b_module": "scanning", "b_class": "NetworkScanner", "b_port": None, "b_status": "network_scanner", "b_parent": None}
    actions.insert(0, scanning_entry)
    with open(path, "w") as f:
        json.dump(actions, f, indent=4)
    print("  Added scanning module to config/actions.json")
else:
    print("  scanning already in config/actions.json")
PY
fi

# Patch shared.py so that when Ragnar regenerates actions.json (e.g. "missing modules") it always includes scanning
SHARED_PY="$RAGNAR_DIR/shared.py"
if [ -f "$SHARED_PY" ]; then
  if ! grep -q "Ensure network scanner in config" "$SHARED_PY" 2>/dev/null; then
    python3 <<PY
path = "$SHARED_PY"
with open(path, "r") as f:
    text = f.read()
old = """            
            try:
                with open(self.actions_file, 'w') as file:
                    json.dump(actions_config, file, indent=4)"""
new = '''            
            # Ensure network scanner in config (orchestrator requires it)
            if not any(a.get('b_module') == 'scanning' for a in actions_config):
                actions_config.insert(0, {"b_module": "scanning", "b_class": "NetworkScanner", "b_port": None, "b_status": "network_scanner", "b_parent": None})
                if "NetworkScanner" not in self.status_list:
                    self.status_list.insert(0, "NetworkScanner")
            try:
                with open(self.actions_file, 'w') as file:
                    json.dump(actions_config, file, indent=4)'''
if old in text and new not in text:
    text = text.replace(old, new)
    with open(path, "w") as f:
        f.write(text)
    print("  Patched shared.py: generate_actions_json will always include scanning")
else:
    print("  shared.py already patched or format changed; skipping")
PY
  fi
fi

# Verify patches were applied correctly
if [ "$DISPLAY_MODE" = "displayhatmini" ]; then
  echo "Verifying Display HAT Mini patches..."
  python3 <<VERIFY
from pathlib import Path
import sys
import os

base = Path("$RAGNAR_DIR")
shared_py = base / "shared.py"
epd_helper_py = base / "epd_helper.py"

errors = []

# Check if directory exists
if not base.exists():
    print(f"✗ Ragnar directory not found: {base}", file=sys.stderr)
    sys.exit(1)

# Check shared.py
if shared_py.exists():
    text = shared_py.read_text()
    if '"displayhatmini"' not in text:
        errors.append("✗ displayhatmini not found in DISPLAY_PROFILES in shared.py")
    else:
        print("✓ displayhatmini found in DISPLAY_PROFILES")
else:
    errors.append(f"✗ shared.py not found at {shared_py}")

# Check epd_helper.py
if epd_helper_py.exists():
    text = epd_helper_py.read_text()
    if '"displayhatmini"' not in text and "'displayhatmini'" not in text:
        errors.append("✗ displayhatmini not found in KNOWN_EPD_TYPES in epd_helper.py")
    else:
        print("✓ displayhatmini found in KNOWN_EPD_TYPES")
    
    if 'if self.epd_type == "displayhatmini":' not in text:
        errors.append("✗ displayhatmini import handler not found in epd_helper.py")
    else:
        print("✓ displayhatmini import handler found in epd_helper.py")
else:
    errors.append(f"✗ epd_helper.py not found at {epd_helper_py}")

if errors:
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)
else:
    print("✓ All Display HAT Mini patches verified successfully")
VERIFY
  if [ $? -ne 0 ]; then
    echo "WARNING: Some patches may not have been applied correctly"
    echo "  This is usually fine if the patches were applied successfully above."
  fi
fi

if [ "$DISPLAY_MODE" = "displayhatmini" ]; then
  echo "Optimizing Ragnar display loop for LCD speed..."
  python3 - <<PY
from pathlib import Path
import re
display_py = Path("$RAGNAR_DIR/display.py")
if display_py.exists():
    text = display_py.read_text()
    text = re.sub(r'time\.sleep\(\s*2(\.0+)?\s*\)', 'time.sleep(0.03)', text)
    text = re.sub(r'time\.sleep\(\s*1(\.0+)?\s*\)', 'time.sleep(0.03)', text)
    text = re.sub(r'time\.sleep\(\s*0\.5\s*\)', 'time.sleep(0.03)', text)
    text = re.sub(r'time\.sleep\(\s*0\.2\s*\)', 'time.sleep(0.02)', text)
    display_py.write_text(text)
PY
  echo "Adding 'Loading Ragnar' + log lines on display during startup..."
  python3 <<PY
from pathlib import Path
display_py = Path("$RAGNAR_DIR/display.py")
if display_py.exists():
    text = display_py.read_text()
    # Block that shows Loading Ragnar + journalctl -u ragnar lines until deferred init
    loading_block = r'''        # Show Loading Ragnar + last ragnar log lines until deferred init (Display HAT Mini)
        try:
            if getattr(self.shared_data, 'config', {}).get('epd_type') == 'displayhatmini':
                import subprocess
                from PIL import Image, ImageDraw
                w, h = self.shared_data.width, self.shared_data.height
                done = getattr(self.shared_data, '_deferred_init_done', None)
                timeout = 30.0
                start = time.time()
                while (time.time() - start) < timeout:
                    try:
                        out = subprocess.check_output(
                            ['journalctl', '-u', 'ragnar', '-n', '6', '--no-pager', '-o', 'short-iso'],
                            timeout=2, text=True)
                        log_lines = [l.strip()[:50] for l in out.strip().splitlines() if l.strip()][-6:]
                    except Exception:
                        log_lines = []
                    img = Image.new('RGB', (w, h), (0, 0, 0))
                    draw = ImageDraw.Draw(img)
                    try:
                        font = ImageDraw.ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
                        font_sm = ImageDraw.ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
                    except Exception:
                        font = ImageDraw.ImageFont.load_default()
                        font_sm = font
                    draw.text((max(0, w//2 - 60), 8), "Loading Ragnar...", font=font, fill=(255, 255, 255))
                    y = 36
                    for line in log_lines:
                        if y + 12 > h:
                            break
                        draw.text((4, y), line, font=font_sm, fill=(255, 255, 255))
                        y += 12
                    self.epd_helper.display_partial(img)
                    if done and done.is_set():
                        break
                    time.sleep(2)
        except Exception:
            pass
        # Wait for deferred initialization (fonts, images) to finish
        # before attempting to render anything.
        if hasattr(self.shared_data, 'wait_for_deferred_init'):'''
    unpatched = """        # Wait for deferred initialization (fonts, images) to finish
        # before attempting to render anything.
        if hasattr(self.shared_data, 'wait_for_deferred_init'):"""
    old_patch = """        # Early draw so display is not black during deferred init (Display HAT Mini)
        try:
            if getattr(self.shared_data, 'config', {}).get('epd_type') == 'displayhatmini':
                from PIL import Image, ImageDraw
                w, h = self.shared_data.width, self.shared_data.height
                img = Image.new('RGB', (w, h), (0, 0, 0))
                draw = ImageDraw.Draw(img)
                try:
                    font = ImageDraw.ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
                except Exception:
                    font = ImageDraw.ImageFont.load_default()
                draw.text((w//2 - 70, h//2 - 12), "Loading Ragnar...", font=font, fill=(255, 255, 255))
                self.epd_helper.display_partial(img)
        except Exception:
            pass
        # Wait for deferred initialization (fonts, images) to finish
        # before attempting to render anything.
        if hasattr(self.shared_data, 'wait_for_deferred_init'):"""
    if old_patch in text and loading_block not in text:
        text = text.replace(old_patch, loading_block)
        display_py.write_text(text)
        print("  Patched display.py: Loading Ragnar + ragnar log lines")
    elif unpatched in text and loading_block not in text:
        text = text.replace(unpatched, loading_block)
        display_py.write_text(text)
        print("  Patched display.py: Loading Ragnar + ragnar log lines")
    else:
        print("  display.py already patched or format changed")
PY
fi

# Boot splash for Display HAT Mini: use script from repo if present, else create it
if [ "$DISPLAY_MODE" = "displayhatmini" ]; then
  mkdir -p "$RAGNAR_DIR/scripts"
  if [ ! -f "$RAGNAR_DIR/scripts/display_boot_splash.py" ]; then
    cat > "$RAGNAR_DIR/scripts/display_boot_splash.py" <<'SPLASH'
#!/usr/bin/env python3
"""Display HAT Mini boot splash: show Booting / Starting Ragnar / boot log / Loading."""
import os
import subprocess
import sys
import time
def _get_boot_log_lines(max_lines=10, line_chars=48):
    try:
        out = subprocess.check_output(
            ["journalctl", "-b", "-n", str(max_lines * 2), "--no-pager", "-o", "short-iso"],
            timeout=5, text=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return ["(journal unavailable)"]
    lines = []
    for raw in out.strip().splitlines():
        raw = (raw or "").strip()
        if not raw:
            continue
        if len(raw) > line_chars:
            while raw:
                lines.append(raw[:line_chars])
                raw = raw[line_chars:].lstrip()
        else:
            lines.append(raw)
        if len(lines) >= max_lines:
            break
    return lines[-max_lines:] if len(lines) > max_lines else lines
def main():
    try:
        from PIL import Image, ImageDraw
        from waveshare_epd import displayhatmini
    except ImportError:
        return 0
    BG, FG = (0, 0, 0), (255, 255, 255)
    try:
        epd = displayhatmini.EPD()
        if epd.init() != 0:
            return 1
        W, H = epd.width, epd.height
        epd.Clear(0)
    except Exception:
        return 1
    try:
        try:
            font_big = __import__("PIL.ImageFont", fromlist=["truetype"]).ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        except Exception:
            font_big = None
        try:
            font_small = __import__("PIL.ImageFont", fromlist=["truetype"]).ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        except Exception:
            font_small = None
        for text, duration in [("Booting...", 2.0), ("Starting Ragnar...", 2.0)]:
            img = __import__("PIL.Image", fromlist=["new"]).Image.new("RGB", (W, H), BG)
            draw = __import__("PIL.ImageDraw", fromlist=["Draw"]).ImageDraw.Draw(img)
            if font_big:
                bbox = draw.textbbox((0, 0), text, font=font_big)
            else:
                bbox = (0, 0, len(text) * 8, 20)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            x, y = (W - tw) // 2, (H - th) // 2
            draw.text((x, y), text, font=font_big, fill=FG)
            epd.display(img)
            time.sleep(duration)
        log_lines = _get_boot_log_lines(max_lines=10, line_chars=48)
        img = __import__("PIL.Image", fromlist=["new"]).Image.new("RGB", (W, H), BG)
        draw = __import__("PIL.ImageDraw", fromlist=["Draw"]).ImageDraw.Draw(img)
        draw.text((4, 2), "Boot log:", font=font_small, fill=FG)
        y = 16
        for line in log_lines:
            if y + 14 > H:
                break
            draw.text((4, y), line[:52], font=font_small, fill=FG)
            y += 13
        epd.display(img)
        time.sleep(6.0)
        img = __import__("PIL.Image", fromlist=["new"]).Image.new("RGB", (W, H), BG)
        draw = __import__("PIL.ImageDraw", fromlist=["Draw"]).ImageDraw.Draw(img)
        text = "Loading..."
        if font_big:
            bbox = draw.textbbox((0, 0), text, font=font_big)
        else:
            bbox = (0, 0, len(text) * 8, 20)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x, y = (W - tw) // 2, (H - th) // 2
        draw.text((x, y), text, font=font_big, fill=FG)
        epd.display(img)
        time.sleep(4.0)
    except Exception:
        pass
    return 0
if __name__ == "__main__":
    sys.exit(main())
SPLASH
  fi
  chmod +x "$RAGNAR_DIR/scripts/display_boot_splash.py"
  BOOT_SPLASH_LINE="ExecStartPre=/usr/bin/python3 $RAGNAR_DIR/scripts/display_boot_splash.py"
  BOOT_SPLASH_ENV="Environment=DISPLAY_BOOT_W=$DISPLAYHATMINI_REF_W DISPLAY_BOOT_H=$DISPLAYHATMINI_REF_H"
else
  BOOT_SPLASH_LINE=""
  BOOT_SPLASH_ENV=""
fi

# Install post-reboot verification script for Display HAT Mini
if [ "$DISPLAY_MODE" = "displayhatmini" ]; then
  cat > "$RAGNAR_DIR/scripts/verify_displayhatmini_boot.sh" <<'VERIFYSH'
#!/usr/bin/env bash
set -euo pipefail

echo "=== Display HAT Mini post-reboot verification ==="
echo
echo "=== 1) Service status ==="
sudo systemctl is-enabled ragnar || true
sudo systemctl is-active ragnar || true
sudo systemctl status ragnar --no-pager -l | sed -n '1,20p'

echo
echo "=== 2) Service env/startup guards ==="
sudo systemctl cat ragnar | sed -n '/^\[Service\]/,/^\[/p' | sed '/^\[$/d' | grep -E "ExecStartPre|Environment=RAGNAR_|ExecStart=" || true

echo
echo "=== 3) waveshare displayhatmini.py sanity ==="
python3 - <<'PY'
import importlib.util
import pathlib

spec = importlib.util.find_spec("waveshare_epd")
if not spec or not spec.submodule_search_locations:
    print("FAIL: waveshare_epd not found")
    raise SystemExit(1)

p = pathlib.Path(spec.submodule_search_locations[0]) / "displayhatmini.py"
print("driver_path:", p)
if not p.exists():
    print("FAIL: displayhatmini.py missing")
    raise SystemExit(1)

t = p.read_text(errors="ignore")
checks = {
    "st7789 import": ("import st7789" in t) or ("import ST7789 as st7789" in t),
    "no RPi.GPIO import": ("import RPi.GPIO" not in t),
    "backlight=13": ("backlight=13" in t),
    "dc=9": ("dc=9" in t),
    "cs=1": ("cs=1" in t),
    "port=0": ("port=0" in t),
}
ok = True
for key, val in checks.items():
    print(f"{'OK' if val else 'FAIL'}: {key}")
    ok = ok and val
if not ok:
    raise SystemExit(2)
PY

echo
echo "=== 4) Ragnar button pin mapping sanity ==="
if [ -f /home/ragnar/Ragnar/displayhatmini_buttons.py ]; then
  grep -nE "PIN_A|PIN_B|PIN_X|PIN_Y" /home/ragnar/Ragnar/displayhatmini_buttons.py || true
else
  echo "WARN: /home/ragnar/Ragnar/displayhatmini_buttons.py not found"
fi

echo
echo "=== 4b) gpiozero / lgpio (menu buttons) ==="
python3 - <<'PY'
try:
    import lgpio  # noqa: F401
    print("OK: lgpio module (apt: python3-lgpio)")
except ImportError:
    print("WARN: lgpio not importable — run: sudo apt install -y python3-lgpio")
try:
    from gpiozero.pins.lgpio import LGPIOFactory
    from gpiozero import Device
    Device.pin_factory = LGPIOFactory()
    print("OK: gpiozero LGPIOFactory")
except Exception as e:
    print("WARN: LGPIOFactory:", e)
PY

echo
echo "=== 5) Runtime import and panel init test ==="
python3 - <<'PY'
import errno
try:
    from waveshare_epd import displayhatmini
    epd = displayhatmini.EPD()
    result = epd.init()
    print("init_return:", result)
    if result != 0:
        raise SystemExit(3)
    epd.Clear(255)
    print("OK: panel clear test")
except OSError as ex:
    if getattr(ex, "errno", None) in (errno.EBUSY, errno.EAGAIN, 16):
        print("SKIP: display GPIO busy (ragnar.service is using the panel). This is expected while Ragnar runs.")
        raise SystemExit(0)
    print("FAIL:", ex)
    raise
except Exception as ex:
    print("FAIL:", ex)
    raise
PY

echo
echo "=== 6) Recent boot logs (Ragnar) ==="
sudo journalctl -u ragnar -b -n 120 --no-pager | tail -n 120

echo
echo "=== 7) GPIO users (detect conflicts) ==="
sudo lsof /dev/gpiochip* 2>/dev/null || echo "No gpiochip users shown (normal sometimes)"

echo
echo "=== DONE ==="
echo "If everything is OK above, setup is healthy."
echo "If screen is still black, test with menu disabled:"
echo "  sudo systemctl edit ragnar"
echo "  [Service]"
echo "  Environment=RAGNAR_SKIP_DHM_BUTTONS=1"
echo "Then run:"
echo "  sudo systemctl daemon-reload && sudo systemctl restart ragnar"
VERIFYSH
  chmod +x "$RAGNAR_DIR/scripts/verify_displayhatmini_boot.sh"
fi

# Optional: boot journal viewer on Display HAT Mini (must complete before ragnar — same SPI bus)
DISPLAY_AFTER_BOOT=""
DISPLAY_WANTS_BOOT=""
if [ "$DISPLAY_MODE" = "displayhatmini" ]; then
  DISPLAY_AFTER_BOOT=" ragnar-display.service"
  DISPLAY_WANTS_BOOT=" ragnar-display.service"
fi

if [ "$DISPLAY_MODE" = "displayhatmini" ]; then
  echo "Installing ragnar-display.service (boot log on HAT Mini, before ragnar)..."
  cat > /etc/systemd/system/ragnar-display.service <<DSVC
[Unit]
Description=Ragnar boot journal on Display HAT Mini
DefaultDependencies=no
After=local-fs.target systemd-journald.socket sysinit.target
Before=ragnar.service
Wants=systemd-journald.socket

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -OO $RAGNAR_DIR/scripts/ragnar_boot_display.py
Environment=RAGNAR_BOOT_DISPLAY_SEC=45
Environment=RAGNAR_NETWORK_SCREEN_SEC=10
Environment=RAGNAR_DIR=$RAGNAR_DIR
Environment=PYTHONUNBUFFERED=1
TimeoutStartSec=120
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
DSVC
  chmod +x "$RAGNAR_DIR/scripts/ragnar_boot_display.py" 2>/dev/null || true
fi

# PiSugar: requirements.txt installs the pip package for everyone, but only users who opted in need the listener.
# Without this, Ragnar keeps trying localhost pisugar-server and logs errors on every boot.
PISUGAR_ENV_LINE=""
if [[ ! "${INSTALL_PISUGAR:-n}" =~ ^[Yy]$ ]]; then
  PISUGAR_ENV_LINE="Environment=RAGNAR_DISABLE_PISUGAR=1"
fi
# PiSugar 3: start Ragnar after pisugar-server so TCP client is not met with connection refused during boot.
# Wants= (not Requires=) so Ragnar still starts if pisugar-server fails.
PISUGAR_AFTER_SUFFIX=""
PISUGAR_WANTS_SUFFIX=""
if [[ "${INSTALL_PISUGAR:-n}" =~ ^[Yy]$ ]]; then
  PISUGAR_AFTER_SUFFIX=" pisugar-server.service"
  PISUGAR_WANTS_SUFFIX=" pisugar-server.service"
  # Listener retries + background reconnect if server is slow after boot
  PISUGAR_CONNECT_ENV="Environment=RAGNAR_PISUGAR_MAX_CONNECT_ATTEMPTS=24
Environment=RAGNAR_PISUGAR_RECONNECT_INTERVAL_SEC=45"
else
  PISUGAR_CONNECT_ENV=""
fi

echo "Creating service..."
cat > /etc/systemd/system/ragnar.service <<SVCEOF
[Unit]
Description=ragnar Service
# Wait for routable network when NM/networkd publish network-online (reduces Wi-Fi race on boot)
After=network-online.target network.target ssh.service$DISPLAY_AFTER_BOOT$PISUGAR_AFTER_SUFFIX
Wants=network-online.target$DISPLAY_WANTS_BOOT$PISUGAR_WANTS_SUFFIX
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
# Short delay so SPI/display is ready after reboot (Display HAT Mini)
ExecStartPre=/bin/sleep 2
$BOOT_SPLASH_LINE
ExecStart=/usr/bin/python3 -OO $RAGNAR_DIR/$RAGNAR_ENTRYPOINT
WorkingDirectory=$RAGNAR_DIR
Restart=always
RestartSec=10
User=root
# Ensure SSH remains accessible
ExecStartPre=/bin/bash -c '/bin/systemctl start ssh || /bin/systemctl start sshd || true'
# Logging
StandardOutput=journal
StandardError=journal
# Environment
Environment=PYTHONUNBUFFERED=1
Environment=RAGNAR_DHM_BUTTON_DELAY=1.0
Environment=RAGNAR_GPIOZERO_FACTORY=lgpio
$BOOT_SPLASH_ENV
$PISUGAR_ENV_LINE
$PISUGAR_CONNECT_ENV
# Timeouts (start can be slow: splash + deferred init + display)
TimeoutStartSec=120
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
SVCEOF

echo "Verifying display setup..."
if [ "$DISPLAY_MODE" = "displayhatmini" ]; then
  echo "Testing Display HAT Mini driver..."
  python3 - <<'PY'
import sys
try:
    from waveshare_epd import displayhatmini
    print("✓ displayhatmini module imported successfully")
    print(f"  EPD class: {displayhatmini.EPD}")
    
    # Test initialization
    try:
        epd = displayhatmini.EPD()
        print("✓ EPD instance created")
        result = epd.init()
        if result == 0:
            print("✓ Display initialized successfully")
            # Test clear
            epd.Clear(0)  # Black screen
            import time
            time.sleep(0.5)
            epd.Clear(255)  # White screen
            print("✓ Display test pattern shown")
        else:
            print(f"✗ Display initialization returned: {result}")
    except Exception as e:
        print(f"✗ Display initialization failed: {e}")
        import traceback
        traceback.print_exc()
except ImportError as e:
    print(f"✗ Failed to import displayhatmini: {e}")
    sys.exit(1)
PY
  if [ $? -ne 0 ]; then
    echo "WARNING: Display verification failed. Check errors above."
  fi
fi

echo "Verifying SPI devices..."
ls /dev/spi* || true

echo "Enabling and starting Ragnar..."
systemctl daemon-reload
if [ "$DISPLAY_MODE" = "displayhatmini" ] && [ -f /etc/systemd/system/ragnar-display.service ]; then
  systemctl enable ragnar-display.service 2>/dev/null || true
  echo "Enabled ragnar-display.service (boot log on HAT Mini ends before ragnar starts)."
fi
systemctl enable ragnar

# Help network-online.target actually wait for Wi-Fi/Ethernet on Bookworm (optional unit)
if systemctl list-unit-files 2>/dev/null | grep -q '^NetworkManager-wait-online.service'; then
  systemctl enable NetworkManager-wait-online.service 2>/dev/null || true
  echo "Enabled NetworkManager-wait-online.service (improves After=network-online.target for ragnar)."
fi
if systemctl list-unit-files 2>/dev/null | grep -q '^systemd-networkd-wait-online.service'; then
  systemctl enable systemd-networkd-wait-online.service 2>/dev/null || true
fi

# Health / pre-reboot tooling
chmod +x "$RAGNAR_DIR/scripts/pre_reboot_check.sh" "$RAGNAR_DIR/scripts/safe_reboot.sh" "$RAGNAR_DIR/scripts/ragnar_startup_selftest.py" "$RAGNAR_DIR/scripts/check_usb_ssh.sh" "$RAGNAR_DIR/scripts/ragnar_boot_display.py" "$RAGNAR_DIR/scripts/validate_boot_files.sh" "$RAGNAR_DIR/scripts/install_pisugar_boot_dropin.sh" "$RAGNAR_DIR/scripts/check_pisugar.sh" 2>/dev/null || true
touch /var/log/ragnar_health.log 2>/dev/null && chmod 644 /var/log/ragnar_health.log 2>/dev/null || true

# Test if Ragnar can start before enabling service
echo "Testing Ragnar startup..."
cd "$RAGNAR_DIR"
if timeout 10 python3 -OO "$RAGNAR_ENTRYPOINT" > /tmp/ragnar_test.log 2>&1 & 
then
  TEST_PID=$!
  sleep 3
  if kill -0 $TEST_PID 2>/dev/null; then
    echo "✓ Ragnar started successfully in test mode"
    kill $TEST_PID 2>/dev/null || true
    wait $TEST_PID 2>/dev/null || true
  else
    echo "⚠ Ragnar test exited quickly. Checking logs..."
    tail -20 /tmp/ragnar_test.log
  fi
else
  echo "⚠ Could not start Ragnar in test mode"
  if [ -f /tmp/ragnar_test.log ]; then
    echo "Test log:"
    tail -20 /tmp/ragnar_test.log
  fi
fi

# Run diagnostics before starting
diagnose_and_fix_service

echo "Starting Ragnar service..."
if ! systemctl start ragnar 2>/dev/null; then
  echo "⚠ Initial start failed. Attempting auto-fix..."
  auto_fix_service_errors
fi

# Final status check
sleep 2
if systemctl is-active --quiet ragnar; then
  echo "✓ Ragnar service is running"
else
  echo "⚠ Ragnar service is not running"
  echo ""
  echo "Service status:"
  systemctl status ragnar --no-pager -l | head -15
  echo ""
  echo "Recent logs:"
  journalctl -u ragnar -n 30 --no-pager
  echo ""
  echo "Troubleshooting:"
  echo "  1. Check logs above for specific errors"
  echo "  2. Verify Python packages: pip3 install --break-system-packages -r $RAGNAR_DIR/requirements.txt"
  echo "  3. Check display driver (if using displayhatmini): python3 -c 'from waveshare_epd import displayhatmini'"
  echo "  4. Check file permissions: ls -la $RAGNAR_DIR/$RAGNAR_ENTRYPOINT"
fi

echo "Re-applying config after first start..."
patch_display_config

# Only restart if service is running
if systemctl is-active --quiet ragnar; then
  echo "Restarting Ragnar to apply config changes..."
  systemctl restart ragnar
  sleep 2
  if systemctl is-active --quiet ragnar; then
    echo "✓ Ragnar restarted successfully"
  else
    echo "⚠ Ragnar failed to restart. Check logs: journalctl -u ragnar -n 50"
  fi
else
  echo "⚠ Ragnar service is not running. Fix errors before restarting."
fi

install_pisugar_support
if [[ "${INSTALL_PISUGAR:-n}" =~ ^[Yy]$ ]] && [[ -x "$RAGNAR_DIR/scripts/install_pisugar_boot_dropin.sh" ]]; then
  echo "Ensuring PiSugar systemd boot drop-in (idempotent)..."
  "$RAGNAR_DIR/scripts/install_pisugar_boot_dropin.sh" || echo "WARNING: PiSugar boot drop-in step failed (non-fatal)."
fi
install_pwnagotchi_bridge

# Show network information
show_network_info

echo ""
echo "Final config check:"
grep -n '"epd_type"\|"ref_width"\|"ref_height"' "$RAGNAR_DIR/config/shared_config.json" || true

echo ""
echo "========================================"
echo " INSTALL COMPLETE"
echo " Safe reboot (runs pre-flight checks): sudo $RAGNAR_DIR/scripts/safe_reboot.sh"
echo " Pre-reboot checks only:              sudo $RAGNAR_DIR/scripts/pre_reboot_check.sh"
echo " Startup self-test:                   sudo RAGNAR_DIR=$RAGNAR_DIR /usr/bin/python3 $RAGNAR_DIR/scripts/ragnar_startup_selftest.py"
echo " Health log:                         /var/log/ragnar_health.log"
echo " USB gadget SSH check:               sudo $RAGNAR_DIR/scripts/check_usb_ssh.sh  (see docs/USB_SSH_GADGET.md)"
echo " Selected mode: $DISPLAY_MODE"
echo " Display setting: $SELECTED_EPD"
if [ "$DISPLAY_MODE" = "displayhatmini" ]; then
  if [ "${DISPLAYHATMINI_REF_W}" = "240" ] && [ "${DISPLAYHATMINI_REF_H}" = "320" ]; then
    DISPLAY_ROT_LABEL="Portrait (240x320 logical, ST7789 rotation 0)"
  else
    DISPLAY_ROT_LABEL="Landscape (320x240 logical, ST7789 rotation 180)"
  fi
  echo " Pins used: SPI port=0, cs=1, dc=9, backlight=13"
  echo " Resolution: ${DISPLAYHATMINI_REF_W}x${DISPLAYHATMINI_REF_H} (logical)"
  echo " Orientation: ${DISPLAY_ROT_LABEL}"
  echo " SPI speed: $DISPLAY_SPI_HZ"
  echo ""
  echo " If display is blank, check:"
  echo "   1. SPI enabled: sudo raspi-config nonint do_spi 0"
  echo "   2. Service logs: journalctl -u ragnar -n 50 --no-pager"
  echo "   3. Test display: python3 -c 'from waveshare_epd import displayhatmini; epd = displayhatmini.EPD(); epd.init(); epd.Clear(255)'"
  echo "   4. Run post-reboot verifier: sudo $RAGNAR_DIR/scripts/verify_displayhatmini_boot.sh"
fi
if [[ "$INSTALL_PWN" =~ ^[Yy]$ ]]; then
  echo " Pwnagotchi bridge: requested"
fi
if [[ "$INSTALL_PISUGAR" =~ ^[Yy]$ ]]; then
  echo " PiSugar support: requested"
fi
if [[ "$CONFIGURE_STATIC_IP" =~ ^[Yy]$ ]] && [ -n "$STATIC_IP" ]; then
  echo " Static IP: $STATIC_IP (interface: $ACTIVE_INTERFACE)"
  echo "   Connect with: ssh ragnar@$STATIC_IP"
else
  # Show current IP if static IP not configured
  CURRENT_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  if [ -n "$CURRENT_IP" ]; then
    echo " Current IP: $CURRENT_IP"
    echo "   Connect with: ssh ragnar@$CURRENT_IP"
    echo "   Note: IP may change after reboot. Set static IP to prevent this."
  fi
fi

# Final service status
echo ""
if systemctl is-active --quiet ragnar; then
  echo "✓ Ragnar service: RUNNING"
else
  echo "⚠ Ragnar service: NOT RUNNING"
  echo "   Check logs: journalctl -u ragnar -n 50 --no-pager"
fi

echo "========================================"
echo ""

read -p "Reboot now? (y/N): " R
if [[ "$R" =~ ^[Yy]$ ]]; then
  if [[ -x "$RAGNAR_DIR/scripts/safe_reboot.sh" ]]; then
    echo "Running pre-reboot validation, then reboot..."
    "$RAGNAR_DIR/scripts/safe_reboot.sh" || echo "Reboot aborted — fix failures and run: sudo $RAGNAR_DIR/scripts/safe_reboot.sh"
  else
    echo "WARNING: safe_reboot.sh missing; using plain reboot (no pre-checks)."
    reboot
  fi
fi
