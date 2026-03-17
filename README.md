image Ragnar
ko-fi GitHub stars Python Status License: MIT

**About this repository** — [DarkSecNetwork/ragnar-displayhatmini](https://github.com/DarkSecNetwork/ragnar-displayhatmini) contains the full Ragnar application (the **Ragnar/** folder) and **install_ragnar.sh**. Clone this repo to your Pi and run `sudo ./install_ragnar.sh` from the repo root; the installer will copy **Ragnar/** to `/home/ragnar/Ragnar`. For Display HAT Mini choose option **9**, then **1** (Landscape) or **2** (Portrait). See [Install Guide](docs/INSTALL.md) for step-by-step instructions.

Ragnar is a fork of the awesome Bjorn project — a Tamagotchi-like autonomous network scanning, vulnerability assessment, and offensive security tool. It runs on a Raspberry Pi with a 2.13-inch e-Paper HAT, as a headless server on Debian-based systems (AMD64/ARM/ARM64) with Ethernet-first connectivity, or on the WiFi Pineapple Pager with full-color LCD display. On servers with 8GB+ RAM, Ragnar unlocks advanced capabilities including real-time traffic analysis and enhanced vulnerability scanning.

Important

For educational and authorized testing purposes only.

Quick Install

**From this repo (recommended — includes Display HAT Mini and full Ragnar bundle):**
```bash
git clone https://github.com/DarkSecNetwork/ragnar-displayhatmini.git
cd ragnar-displayhatmini
sudo ./install_ragnar.sh
```

**Or script only (no clone):**
```bash
wget https://raw.githubusercontent.com/DarkSecNetwork/ragnar-displayhatmini/main/install_ragnar.sh
sudo chmod +x install_ragnar.sh && sudo ./install_ragnar.sh
```

On Raspberry Pi: choose e-Paper HAT, Display HAT Mini (option 9), server/headless, or Pineapple Pager. On other hardware: server install or Pineapple Pager. Reboot when it finishes.

For detailed information see the [Install Guide](docs/INSTALL.md). See Release Notes for what's new.

🌐 Web Interface
Access Ragnar's dashboard at http://<ragnar-ip>:8000

Real-time network discovery and vulnerability scanning
Multi-source threat intelligence dashboard
File management with image gallery
System monitoring and configuration
Hardware profile auto-detection (Pi Zero 2W, Pi 4, Pi 5)
WiFi Configuration Portal — When Ragnar can't connect to a known network, it creates a WiFi hotspot:

Connect to WiFi network Ragnar (password: ragnarconnect)
Navigate to http://192.168.4.1:8000
Configure your WiFi credentials via the mobile-friendly interface
Ragnar will automatically retry known WiFi after some time if the AP is unused
Once configured, Ragnar exits AP mode and connects to your network
The portal supports network scanning with signal strength, manual entry for hidden SSIDs, known network management, and one-tap reconnection.

🌟 Features
Wi-Fi Client Isolation Testing — AirSnitch tests whether a network properly isolates clients using GTK abuse, gateway bouncing, and port stealing attacks. See AirSnitch Guide
Network Scanning — Identifies live hosts and open ports
Vulnerability Assessment — Scans using Nmap and other tools
Multi-Source Threat Intelligence — Real-time fusion from CISA KEV, NVD CVE, AlienVault OTX, and MITRE ATT&CK
AI-Powered Analysis — GPT-5 Nano integration for security summaries, vulnerability prioritization, and remediation advice. See AI Integration Guide
System Attacks — Brute-force attacks on FTP, SSH, SMB, RDP, Telnet, SQL
File Stealing — Extracts data from vulnerable services
Advanced Server Features (8GB+ RAM) — Real-time traffic analysis, advanced vulnerability scanning with Nuclei/Nikto/SQLMap/ZAP, parallel scanning, and CVE correlation. See Server Mode
LAN-First Connectivity — Prefers Ethernet when present, manages WiFi as fallback
Smart WiFi Management — Auto-connects to known networks, falls back to AP mode, captive portal for configuration
E-Paper Display — Real-time status showing targets, vulnerabilities, credentials, and network info
WiFi Pineapple Pager — Full-color LCD display with button controls, LED indicators, and auto-dim. See Pager section
Hardware-Bound Authentication — Optional login with full database encryption at rest. See Security & Authentication
PiSugar 3 Button — Physical button to swap between Ragnar and Pwnagotchi modes
Kill Switch — Built-in endpoint (/api/kill) to wipe all databases, logs, and data. See Kill Switch
Comprehensive Logging — All nmap commands and results logged to data/logs/nmap.log
image

image
📌 Supported Platforms & Prerequisites
Raspberry Pi (Zero W / W2 / 4 / 5)
64-bit Raspberry Pi OS (Debian Trixie, kernel 6.12+)
Username and hostname set to ragnar
2.13-inch e-Paper HAT connected to GPIO pins (for display mode)
For 32-bit systems, use Ragnar's predecessor Bjorn
Recommendation: Edit ~/.config/labwc/autostart and comment out /usr/bin/lwrespawn /usr/bin/wf-panel-pi & to free up resources, or run sudo pkill wf-panel-pi temporarily.

Debian-Based Server / Headless
Debian 11+ or Ubuntu 20.04+ (AMD64, ARM64, or ARMv7)
Minimum: 2GB RAM, 2 CPU cores, 10GB free disk
Recommended: 8GB+ RAM for advanced features (traffic analysis, Nuclei, Nikto, SQLMap)
WiFi Pineapple Pager
Firmware 1.0.7+
PAGERCTL payload installed (provides libpagerctl.so)
SSH access from your workstation
Python3 + nmap (auto-installed on first run)
MIPS-compiled Python libraries bundled in pager_lib/ (or sourced from PAGERCTL payload)
🔨 Installation Details
The installer auto-detects your platform and configures everything:

Distro detection — Supports apt, dnf, pacman, zypper
Architecture support — AMD64, ARM64, ARMv7, ARMv8
Profiles — Pi + e-Paper, Server/Headless, WiFi Pineapple Pager
Automatic advanced tools — Systems with 8GB+ RAM get advanced features installed automatically
Smart resource management — Pi Zero W/W2 automatically skip resource-intensive tools
ARM optimizations — Uses PiWheels on ARM, retries mirrors, skips Pi-only steps on other hardware
For the full installation walkthrough see the [Install Guide](docs/INSTALL.md).

🖥️ Server Mode: Advanced Features (8GB+ RAM)
When deployed on systems with 8GB+ RAM, Ragnar automatically unlocks advanced security capabilities.

Fresh installs: The main installer detects 8GB+ RAM and installs advanced tools automatically.

Existing installs: Run the advanced tools installer separately:

cd /home/ragnar/Ragnar
sudo ./scripts/install_advanced_tools.sh
sudo systemctl restart ragnar
Real-Time Traffic Analysis
Live packet capture with tcpdump and tshark
Connection tracking with detailed TCP/UDP statistics
Deep protocol inspection (HTTP, DNS, SMB, SSH)
Per-host bandwidth monitoring and top talkers
Automated security risk scoring and anomaly detection
DNS query logging and port activity monitoring
Advanced Vulnerability Scanning
OWASP ZAP — Spider + AJAX spider + active scan with automatic browser detection
Authenticated scanning — 8 auth types: form-based, HTTP Basic, OAuth2, Bearer Token, API Key, Cookie, Script-based
Nuclei — 5000+ vulnerability templates from ProjectDiscovery
Nikto — Comprehensive web server assessment
SQLMap — Automated SQL injection detection
Parallel scanning — Multi-threaded for faster results
CVE correlation — Automatic correlation with NVD, CISA KEV, and threat feeds
Live progress — Real-time log panel and animated progress bar
Web and API modes — Scan web apps or API endpoints with OpenAPI spec import
What Gets Installed
Traffic tools: tcpdump, tshark, ngrep, iftop, nethogs
Vulnerability scanners: Nuclei, Nikto, SQLMap, WhatWeb
Web app security: OWASP ZAP (requires Java)
Nmap scripts: vulners.nse, vulscan database
Ragnar auto-detects available tools and enables corresponding features in the web interface.

🐝 Ragnar + Pwnagotchi Side by Side
A bundled helper script plus dashboard controls make swapping between Ragnar and Pwnagotchi painless:

Run the installer:

cd /home/ragnar/Ragnar
sudo ./scripts/install_pwnagotchi.sh
The script clones pwnagotchiworking into /opt/pwnagotchi, installs dependencies, writes /etc/pwnagotchi/config.toml, and drops a disabled pwnagotchi.service. Re-running is fast — it skips already-installed packages.

Open the web UI → Config tab → Pwnagotchi Bridge → click Switch to Pwnagotchi.

Requirements:

USB WiFi adapter (wlan1) with monitor mode support
Waveshare 2.13" e-Paper HAT V4 for the pwnagotchi face display
Pwnagotchi web UI: http://<same-ip>:8080 (credentials: ragnar / ragnar)

What the installer configures:

Monitor mode scripts (/usr/bin/monstart, /usr/bin/monstop)
e-Paper display type (waveshare213_v4) and rotation
Web UI on port 8080, Pwngrid disabled
RSA keys, log directories, bettercap integration
Swapping via PiSugar 3 button:

Button Action	While Ragnar is running	While Pwnagotchi is running
Single tap	Toggle manual mode	—
Double tap	Switch to Pwnagotchi	Switch to Ragnar
Long press	Switch to Pwnagotchi	Switch to Ragnar
A 10-second cooldown prevents accidental double triggers. If PiSugar is not connected, the listener is silently disabled.

Static IP recommended: When switching modes, WiFi may briefly reconnect with a different DHCP IP. Set a static IP:

sudo nmcli con mod "YOUR_WIFI_SSID" ipv4.method manual \
  ipv4.addresses "192.168.1.211/24" \
  ipv4.gateway "192.168.1.1" \
  ipv4.dns "192.168.1.1"
sudo nmcli con up "YOUR_WIFI_SSID"
Or set a DHCP reservation on your router. This only affects wlan0 — the monitor interface (wlan1/mon0) is not changed.

Service recovery: If Ragnar doesn't start after a reboot:

sudo /home/ragnar/Ragnar/scripts/fix_services.sh
🍍 WiFi Pineapple Pager
Ragnar can be deployed to the WiFi Pineapple Pager as a native payload with full-color LCD display, button controls, and LED status indicators.

Features on Pager:

Full-color 480x222 LCD with Viking-themed status display
Physical button controls (navigate menus, pause/resume, adjust brightness)
LED indicators (blue=idle, cyan=scanning, red=brute force, yellow=stealing)
Graphical startup menu with interface selection and Web UI toggle
Auto-dim for battery saving and payload handoff support
Installation:

Option A — From the main installer (select option 3):

sudo ./install_ragnar.sh
# Choose: 3. Install on WiFi Pineapple Pager
Option B — Direct deployment:

./scripts/install_pineapple_pager.sh [pager-ip]
Usage:

Launch from Pager menu: Reconnaissance > PagerRagnar
Press GREEN to confirm the splash screen
Select network interface and toggle Web UI on/off
Press GREEN on "Start Ragnar" to begin scanning
Press RED while running to open the pause menu
🤝 Contributing
The project welcomes contributions in new attack modules, bug fixes, documentation, and feature improvements.

See Contributing Docs and Code of Conduct.

📫 Contact
Report Issues: Via [GitHub Issues](https://github.com/DarkSecNetwork/ragnar-displayhatmini/issues)
This repo: [DarkSecNetwork/ragnar-displayhatmini](https://github.com/DarkSecNetwork/ragnar-displayhatmini) — Ragnar by [PierreGode/Ragnar](https://github.com/PierreGode/Ragnar)
📜 License
2025 - Ragnar is distributed under the MIT License. See the LICENSE file for details.