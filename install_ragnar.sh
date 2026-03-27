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
echo " Ragnar Installer v6.2"
echo "========================================"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this script with sudo."
  exit 1
fi

# Directory where this installer script lives (for local repo install)
INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

configure_static_ip() {
  echo
  echo "========================================"
  echo " Static IP Configuration"
  echo "========================================"
  echo
  echo "Setting a static IP prevents connection issues after reboot."
  echo "You can skip this and configure it later if needed."
  echo
  read -p "Configure static IP? (y/N): " CONFIGURE_STATIC_IP
  
  if [[ ! "$CONFIGURE_STATIC_IP" =~ ^[Yy]$ ]]; then
    echo "Skipping static IP configuration."
    return 0
  fi
  
  # Detect active network interface
  ACTIVE_INTERFACE=$(ip route | grep default | awk '{print $5}' | head -1)
  if [ -z "$ACTIVE_INTERFACE" ]; then
    # Fallback detection
    if ip link show wlan0 >/dev/null 2>&1; then
      ACTIVE_INTERFACE="wlan0"
    elif ip link show eth0 >/dev/null 2>&1; then
      ACTIVE_INTERFACE="eth0"
    else
      echo "WARNING: Could not detect network interface. Skipping static IP."
      return 1
    fi
  fi
  
  echo
  echo "Detected active interface: $ACTIVE_INTERFACE"
  echo
  
  # Get current network info
  CURRENT_IP=$(ip addr show "$ACTIVE_INTERFACE" | grep "inet " | awk '{print $2}' | cut -d/ -f1)
  CURRENT_GATEWAY=$(ip route | grep default | awk '{print $3}' | head -1)
  
  if [ -n "$CURRENT_IP" ]; then
    echo "Current IP: $CURRENT_IP"
    echo "Current Gateway: $CURRENT_GATEWAY"
    echo
    read -p "Use current IP as static IP? (Y/n): " USE_CURRENT
    if [[ ! "$USE_CURRENT" =~ ^[Nn]$ ]]; then
      STATIC_IP="$CURRENT_IP"
      STATIC_GATEWAY="$CURRENT_GATEWAY"
    else
      read -p "Enter static IP address (e.g., 192.168.1.100): " STATIC_IP
      read -p "Enter gateway/router IP (e.g., 192.168.1.1): " STATIC_GATEWAY
    fi
  else
    read -p "Enter static IP address (e.g., 192.168.1.100): " STATIC_IP
    read -p "Enter gateway/router IP (e.g., 192.168.1.1): " STATIC_GATEWAY
  fi
  
  # Validate IP format (basic)
  if [[ ! "$STATIC_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "ERROR: Invalid IP address format. Skipping static IP configuration."
    return 1
  fi
  
  if [[ ! "$STATIC_GATEWAY" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "ERROR: Invalid gateway format. Skipping static IP configuration."
    return 1
  fi
  
  # Extract subnet from IP (assume /24)
  SUBNET=$(echo "$STATIC_IP" | cut -d. -f1-3)
  STATIC_IP_WITH_MASK="${STATIC_IP}/24"
  
  # Ask for DNS (optional, with defaults)
  read -p "Enter DNS servers (default: 8.8.8.8 1.1.1.1): " STATIC_DNS
  STATIC_DNS="${STATIC_DNS:-8.8.8.8 1.1.1.1}"
  
  echo
  echo "Configuration summary:"
  echo "  Interface: $ACTIVE_INTERFACE"
  echo "  IP Address: $STATIC_IP_WITH_MASK"
  echo "  Gateway: $STATIC_GATEWAY"
  echo "  DNS: $STATIC_DNS"
  echo
  read -p "Apply this configuration? (Y/n): " CONFIRM
  
  if [[ "$CONFIRM" =~ ^[Nn]$ ]]; then
    echo "Skipping static IP configuration."
    return 0
  fi

  # Raspberry Pi OS Bookworm often uses NetworkManager for wlan0/eth0. dhcpcd.conf alone is IGNORED then.
  NM_CONN=""
  if command -v nmcli >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager 2>/dev/null; then
    NM_CONN=$(nmcli -t -f NAME,DEVICE connection show --active 2>/dev/null | awk -F: -v d="$ACTIVE_INTERFACE" '$2==d {print $1; exit}')
    if [ -z "$NM_CONN" ]; then
      NM_CONN=$(nmcli -t -f NAME,DEVICE connection show 2>/dev/null | awk -F: -v d="$ACTIVE_INTERFACE" '$2==d {print $1; exit}')
    fi
  fi

  if [ -n "$NM_CONN" ]; then
    echo ""
    echo "Using NetworkManager (Bookworm default) — applying static IP via nmcli."
    echo "Connection: $NM_CONN  Device: $ACTIVE_INTERFACE"
    DNS_COMMA=$(echo "$STATIC_DNS" | tr ' ' ',')
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
      echo "After reboot, connect with: ssh ragnar@$STATIC_IP"
      echo "If SSH still fails, use HDMI+keyboard or Ethernet and run: nmcli connection show \"$NM_CONN\""
      return 0
    fi
  else
    if systemctl is-active --quiet NetworkManager 2>/dev/null; then
      echo ""
      echo "WARNING: NetworkManager is active but no nmcli connection was found for $ACTIVE_INTERFACE."
      echo "Falling back to dhcpcd.conf (may NOT apply on Bookworm — prefer fixing NetworkManager)."
    fi
  fi

  # Fallback: dhcpcd (older Pi OS / images without NM on this interface)
  DHCPCD_CONF="/etc/dhcpcd.conf"

  if [ ! -f "$DHCPCD_CONF" ]; then
    echo "WARNING: $DHCPCD_CONF not found and NetworkManager path not used. Static IP may not persist."
  fi

  if [ -f "$DHCPCD_CONF" ]; then
    cp "$DHCPCD_CONF" "${DHCPCD_CONF}.backup.$(date +%Y%m%d_%H%M%S)"
    sed -i "/^interface $ACTIVE_INTERFACE$/,/^$/d" "$DHCPCD_CONF"
    cat >> "$DHCPCD_CONF" <<EOF

# Static IP configuration for $ACTIVE_INTERFACE (configured by Ragnar installer)
interface $ACTIVE_INTERFACE
static ip_address=$STATIC_IP_WITH_MASK
static routers=$STATIC_GATEWAY
static domain_name_servers=$STATIC_DNS
EOF
    echo "Static IP configuration added to $DHCPCD_CONF"
  fi

  echo ""
  echo "NOTE: With dhcpcd fallback, static IP often requires a reboot on Pi OS."
  echo "After reboot, connect with: ssh ragnar@$STATIC_IP"

  echo ""
  read -p "Apply static IP now (restart dhcpcd)? (y/N): " APPLY_NOW
  if [[ "$APPLY_NOW" =~ ^[Yy]$ ]]; then
    echo "Applying..."
    systemctl restart dhcpcd 2>/dev/null || systemctl restart networking 2>/dev/null || true
    sleep 3
    NEW_IP=$(ip addr show "$ACTIVE_INTERFACE" | grep "inet " | awk '{print $2}' | cut -d/ -f1)
    if [ "$NEW_IP" = "$STATIC_IP" ]; then
      echo "✓ Static IP applied successfully: $NEW_IP"
    else
      echo "⚠ Current IP: ${NEW_IP:-none} — reboot may be required for dhcpcd."
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
  echo " PiSugar power manager"
  echo "========================================"
  # Do NOT use: curl ... | bash  — that feeds the script on stdin, so whiptail/dialog
  # cannot read keyboard input and model selection appears broken.
  # Run from a file so stdin stays the terminal (use: ssh -t user@pi for SSH).
  PISUGAR_TMP="$(mktemp /tmp/pisugar-power-manager-XXXXXX.sh)"
  if ! curl -sSL -f "http://cdn.pisugar.com/release/pisugar-power-manager.sh" -o "$PISUGAR_TMP"; then
    echo "WARNING: Could not download PiSugar installer."
    rm -f "$PISUGAR_TMP"
    return 1
  fi
  chmod +x "$PISUGAR_TMP"
  if [ -t 0 ]; then
    echo "Interactive mode: you can choose your PiSugar model in the prompts."
    echo "(If prompts still fail, use: ssh -t ... so SSH allocates a terminal.)"
    unset DEBIAN_FRONTEND
  else
    echo "WARNING: No TTY on stdin — interactive PiSugar dialogs will not work."
    echo "Re-run this installer from a real terminal, or run manually after install:"
    echo "  curl -sSL http://cdn.pisugar.com/release/pisugar-power-manager.sh -o /tmp/p.sh && sudo bash /tmp/p.sh"
    export DEBIAN_FRONTEND=noninteractive
  fi
  if bash "$PISUGAR_TMP"; then
    echo "PiSugar installer finished."
    if [ ! -t 0 ]; then
      echo "If hardware is attached, run: sudo dpkg-reconfigure pisugar-server"
    fi
    systemctl enable pisugar-server 2>/dev/null || true
    systemctl start pisugar-server 2>/dev/null || true
  else
    echo "WARNING: PiSugar install failed or was cancelled. You can run it later:"
    echo "  curl -sSL http://cdn.pisugar.com/release/pisugar-power-manager.sh -o /tmp/p.sh && sudo bash /tmp/p.sh"
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

echo "Applying boot performance tuning..."
append_if_missing "dtparam=spi=on" "$CONFIG_TXT"
append_if_missing "gpu_mem=128" "$CONFIG_TXT"
append_if_missing "core_freq=500" "$CONFIG_TXT"
append_if_missing "core_freq_min=500" "$CONFIG_TXT"
# Disable activity LED (green) so it doesn't blink while Ragnar runs
append_if_missing "dtparam=act_led_trigger=none" "$CONFIG_TXT"
# Fallback for older Raspberry Pi OS (config in /boot)
[ -f /boot/config.txt ] && append_if_missing "dtparam=act_led_trigger=none" "/boot/config.txt" || true

select_display
ask_optional_features
configure_static_ip

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

echo "Creating service..."
cat > /etc/systemd/system/ragnar.service <<SVCEOF
[Unit]
Description=ragnar Service
After=network.target ssh.service

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
Environment=RAGNAR_DHM_BUTTON_DELAY=2.5
Environment=RAGNAR_GPIOZERO_FACTORY=lgpio
$BOOT_SPLASH_ENV
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
systemctl enable ragnar

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
install_pwnagotchi_bridge

# Show network information
show_network_info

echo ""
echo "Final config check:"
grep -n '"epd_type"\|"ref_width"\|"ref_height"' "$RAGNAR_DIR/config/shared_config.json" || true

echo ""
echo "========================================"
echo " INSTALL COMPLETE"
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
  reboot
fi
