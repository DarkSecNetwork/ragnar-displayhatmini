# Install Guide

This is the Install Guide linked from the main [README](../README.md). Use **Raspberry Pi Imager** to install your OS:  
https://www.raspberrypi.com/software/

When imaging, set **hostname** and **username** to `ragnar` so the installer and paths match this guide.

---

## Prerequisites

**Raspberry Pi Zero W2 (64-bit)** is a common target. Ragnar was not developed specifically for it, but many users run it successfully on this board.

- **Raspberry Pi OS** (64-bit). Tested with:
  - Kernel 6.6, Debian GNU/Linux 13 (trixie)
- **Hostname and username:** `ragnar` (set in Pi Imager or on first boot).
- **Display:** 2.13" e-Paper HAT (V1–V4, 2.7", 2.9", 3.7") or **Display HAT Mini** (320×240 IPS LCD). Connect before install.
- **Optional:** [PiSugar 3 / UPS](https://www.pisugar.com/) — the installer runs PiSugar’s official **Power Manager** script from [PiSugar 3 Series (wiki)](https://github.com/PiSugar/PiSugar/wiki/PiSugar-3-Series#software-installation): **`https://cdn.pisugar.com/release/pisugar-power-manager.sh`** with **`-c release`**, matching their documented install. The vendor script may still show **model selection**; use **`ssh -t ragnar@<pi-ip>`** or a local console so prompts work. The installer **does not** pipe `curl … | bash` (that breaks whiptail); it saves the script and runs it from a file. After hardware is attached, optional firmware OTA: `curl -sSL https://cdn.pisugar.com/release/PiSugarUpdate.sh | sudo bash` (see wiki **OTA firmware upgrade**).

E-Paper V2 and V4 are well tested; V1 and V3 should work. Display HAT Mini is fully supported (option 9 in the installer).

---

## Quick Install (recommended)

Use the automated installer. This repo ([DarkSecNetwork/ragnar-displayhatmini](https://github.com/DarkSecNetwork/ragnar-displayhatmini)) includes the full Ragnar app in the **Ragnar/** folder; when you run **install_ragnar.sh** from the repo directory, it copies **Ragnar/** to `/home/ragnar/Ragnar` on the Pi. If you run the script from a place that has no **Ragnar/** folder (e.g. after only downloading the script), it clones this repo and uses its **Ragnar/** folder, or falls back to [PierreGode/Ragnar](https://github.com/PierreGode/Ragnar) if needed.

### Step 1: Get the repo onto the Pi

Clone or copy the **entire** repository so that `install_ragnar.sh` and the `Ragnar/` folder are in the same directory:

```bash
# Clone this repo
git clone https://github.com/DarkSecNetwork/ragnar-displayhatmini.git
cd ragnar-displayhatmini

# Or copy the whole repo folder via SCP/USB; then cd into it.
```

**Windows users:** Use **LF** line endings for `install_ragnar.sh`. In VS Code/Cursor set the file to "LF" before copying. If the script fails on the Pi with "No such file or directory", fix line endings:  
`sed -i 's/\r$//' install_ragnar.sh`

### Step 2: Run the installer

```bash
sudo ./install_ragnar.sh
```

### Step 3: Follow the prompts (step-by-step)

1. **Display type (1–10)**  
   - **1–4:** e-Paper 2.13" V1–V4  
   - **5–8:** e-Paper 2.7", 2.9", 3.7"  
   - **9:** **Display HAT Mini** (320×240 LCD) — then choose **1** (Landscape) or **2** (Portrait)  
   - **10:** Headless (no display)

2. **Pwnagotchi bridge?**  
   - `y` to install the bridge (same SD card as Pwnagotchi); `N` to skip.

3. **PiSugar?**  
   - `y` if you have a PiSugar battery; `N` otherwise.

4. **Static IP?**  
   - `y` to set a fixed IP (recommended so SSH address doesn’t change); follow the prompts.  
   - `N` to skip (use DHCP).

5. Wait for the script to finish. It will:
   - Install apt and pip packages  
   - Copy **Ragnar/** from this repo to `/home/ragnar/Ragnar` (or installer clones [ragnar-displayhatmini](https://github.com/DarkSecNetwork/ragnar-displayhatmini) / upstream Ragnar if not run from this repo)  
   - Install Waveshare e-Paper library  
   - If Display HAT Mini: create the compatibility driver and use **Ragnar/scripts/display_boot_splash.py** from the repo (or create it if missing)  
   - Patch Ragnar for your display and create the systemd service  

6. **Reboot** when prompted (or when you’re done). After reboot, Ragnar starts automatically.

---

## Step-by-step: What the installer does

If you want to know exactly what runs when you execute `install_ragnar.sh`, here is the order of operations:

**Maintainers:** automated checks and release criteria — [INSTALLER_VALIDATION.md](INSTALLER_VALIDATION.md).

1. **Checks** — Ensures script is run with `sudo`.
2. **Display selection** — You choose display type (1–10); for Display HAT Mini you choose Landscape or Portrait.
3. **Optional features** — You choose whether to install Pwnagotchi bridge and PiSugar.
4. **Static IP** — Optional. You choose the **interface**: **wlan0**, **eth0**, or **usb0** (USB Ethernet gadget for SSH from a PC). On **Pi OS Bookworm**, **NetworkManager** is used when available. **usb0** also enables **`dtoverlay=dwc2`** and **`modules-load=dwc2,g_ether`** in cmdline. See [USB_SSH_GADGET.md](USB_SSH_GADGET.md).
5. **User** — Ensures user `ragnar` exists; creates `/home/ragnar` if needed.
6. **Ragnar directory** — Removes any existing `/home/ragnar/Ragnar`. If the installer is run from this repo (directory containing **Ragnar/** with **Ragnar.py**), it copies that folder to `/home/ragnar/Ragnar`. Otherwise it clones [DarkSecNetwork/ragnar-displayhatmini](https://github.com/DarkSecNetwork/ragnar-displayhatmini) and uses its **Ragnar/** folder, or falls back to `https://github.com/PierreGode/Ragnar.git`.
7. **Waveshare library** — Clones the Waveshare e-Paper repo and installs the RaspberryPi/JetsonNano Python package.
8. **Python dependencies** — Installs `requirements.txt` from Ragnar and extra packages (e.g. `st7789`, `paramiko`, `RPi.GPIO`). For Display HAT Mini, installs `gpiod` and `gpiodevice`.
9. **Display HAT Mini (if option 9):**  
   - Finds the `waveshare_epd` package path and writes `displayhatmini.py` (compatibility driver) with the correct width/height/rotation for st7789.  
   - Patches `shared.py` and `epd_helper.py` for Display HAT Mini; creates data dirs and dictionary files. Uses **Ragnar/scripts/display_boot_splash.py** from the repo if present, otherwise creates it.
10. **Config** — Writes `config/shared_config.json` (and related) for the chosen display.
11. **Patches** — Ensures scanning is in `actions.json` and that Display HAT Mini buffer validation is skipped where needed.
12. **Boot** — Backs up `config.txt` / `cmdline.txt`, enables SPI, optional USB gadget / static IP, applies `gpu_mem` with validation, then validates boot files (restores `.ragnar.bak` on failure). Does **not** disable the green ACT LED (older installs may remove a prior `act_led_trigger=none` line).
13. **Service** — Creates `/etc/systemd/system/ragnar.service`: runs after network and SSH, 2s delay, optional boot splash (Display HAT Mini), then `python3 -OO /home/ragnar/Ragnar/Ragnar.py` (or `headlessRagnar.py` for headless); `WorkingDirectory=/home/ragnar/Ragnar`; restart always.
14. **Enable & start** — `systemctl daemon-reload`, `systemctl enable ragnar`, starts the service.
15. **Optional** — Runs PiSugar installer and Pwnagotchi bridge script if you chose them.

All paths used by the service are under **`/home/ragnar/Ragnar`** (capital R).

---

## Manual Install (without the script)

Use this if you prefer to install Ragnar by hand. The result should match what the installer does: Ragnar in `/home/ragnar/Ragnar`, same dependencies, and a systemd service that runs `Ragnar.py` from that directory.

### Step 1: Activate SPI and I2C

```bash
sudo raspi-config
```

- **Interface Options** → enable **SPI** and **I2C**.

### Step 2: System dependencies

```bash
sudo apt-get update && sudo apt-get upgrade -y

sudo apt install -y \
  libjpeg-dev zlib1g-dev libpng-dev python3-dev libffi-dev libssl-dev \
  libgpiod-dev libcap-dev libi2c-dev libopenjp2-7 libopenblas-dev \
  build-essential python3-pip wget lsof git nmap bluez bluez-tools \
  bridge-utils network-manager i2c-tools rfkill

sudo nmap --script-updatedb
```

### Step 3: User and Ragnar directory

```bash
sudo adduser --disabled-password --gecos "" ragnar 2>/dev/null || true
sudo mkdir -p /home/ragnar
sudo chown ragnar:ragnar /home/ragnar

cd /home/ragnar
sudo rm -rf Ragnar
git clone https://github.com/DarkSecNetwork/ragnar-displayhatmini.git
cp -a ragnar-displayhatmini/Ragnar /home/ragnar/Ragnar
cd /home/ragnar/Ragnar
```

### Step 4: Waveshare e-Paper library

```bash
cd /home/ragnar
git clone --depth=1 --filter=blob:none --sparse https://github.com/waveshareteam/e-Paper.git
cd e-Paper && git sparse-checkout set RaspberryPi_JetsonNano
cd RaspberryPi_JetsonNano/python
sudo pip3 install --break-system-packages --ignore-installed .
cd /home/ragnar/Ragnar
```

### Step 5: Python requirements

```bash
cd /home/ragnar/Ragnar
sudo pip3 install --break-system-packages -r requirements.txt
sudo pip3 install --break-system-packages paramiko st7789 luma.lcd luma.core pandas pandas-stubs Flask-SQLAlchemy openai RPi.GPIO "cryptography<45"
```

For **Display HAT Mini** you must also patch Ragnar and add the compatibility driver (easiest is to run the installer once). Otherwise, install:  
`sudo pip3 install --break-system-packages gpiod gpiodevice`

### Step 6: Configure display type

Edit `/home/ragnar/Ragnar/config/shared_config.json` and set `epd_type` to your display, e.g.:

- `"epd_type": "epd2in13"` (V1)
- `"epd_type": "epd2in13_V2"`
- `"epd_type": "epd2in13_V3"`
- `"epd_type": "epd2in13_V4"`
- `"epd_type": "displayhatmini"` (only if you’ve added the driver and patches)

### Step 7: File descriptor limits (recommended)

To avoid *Too many open files*:

- **limits.conf:** add `* soft nofile 65535`, `* hard nofile 65535`, and same for `root`.
- **systemd:** in `/etc/systemd/system.conf` and `/etc/systemd/user.conf`, set `DefaultLimitNOFILE=65535`.
- **PAM:** in `/etc/pam.d/common-session` and `common-session-noninteractive`, add `session required pam_limits.so`.
- **sysctl:** in `/etc/sysctl.conf` add `fs.file-max = 2097152`, then run `sudo sysctl -p`.
- Run `sudo systemctl daemon-reload`.

### Step 8: Ragnar systemd service

Create `/etc/systemd/system/ragnar.service`:

```ini
[Unit]
Description=ragnar Service
After=network.target ssh.service

[Service]
Type=simple
ExecStartPre=/bin/sleep 2
ExecStart=/usr/bin/python3 -OO /home/ragnar/Ragnar/Ragnar.py
WorkingDirectory=/home/ragnar/Ragnar
Restart=always
RestartSec=10
User=root
ExecStartPre=/bin/bash -c '/bin/systemctl start ssh || /bin/systemctl start sshd || true'
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1
TimeoutStartSec=120
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ragnar
sudo systemctl start ragnar
```

For **headless**, use `ExecStart=/usr/bin/python3 -OO /home/ragnar/Ragnar/headlessRagnar.py` instead.

### Step 9: Data files (if Ragnar complains)

If the app reports missing dictionary or users file:

```bash
sudo mkdir -p /home/ragnar/Ragnar/data/input/dictionary
printf '%s\n' admin root user administrator test guest | sudo tee /home/ragnar/Ragnar/data/input/dictionary/users.txt
printf '%s\n' password 123456 admin root password123 123 test guest | sudo tee /home/ragnar/Ragnar/data/input/dictionary/passwords.txt
sudo chown -R ragnar:ragnar /home/ragnar/Ragnar/data
```

---

## Pwnagotchi Bridge

Running Ragnar and Pwnagotchi on the same SD card is supported via a helper script and the Ragnar web UI.

1. **Install the bridge (on the Pi):**
   ```bash
   cd /home/ragnar/Ragnar
   sudo ./scripts/install_pwnagotchi.sh
   ```
   The script installs dependencies, the `pwnagotchi` Python package, clones the Pwnagotchi repo to `/opt/pwnagotchi`, and adds a systemd unit (disabled by default so Ragnar stays in control).

2. **In the Ragnar web UI:** Open the dashboard → **Config** → **Pwnagotchi Bridge**.
   - **Install or Repair** — re-runs the script.
   - **Switch to Pwnagotchi** — stop Ragnar, start Pwnagotchi (SSH may drop).
   - **Return to Ragnar** — switch back (often after a reboot).

3. A status card in the **Discovered** tab shows bridge status and last switch time.

Re-running the script is safe (idempotent).

---

## After install

- **Web UI:** `http://<pi-ip>:8000` (replace with your Pi’s IP or hostname).
- **Logs:** `sudo journalctl -u ragnar -n 100 --no-pager` or `sudo journalctl -u ragnar -f`.
- **Restart:** `sudo systemctl restart ragnar`.
- **Paths:** Ragnar lives in `/home/ragnar/Ragnar`; config in `/home/ragnar/Ragnar/config/`.

See [TROUBLESHOOTING](TROUBLESHOOTING.md) for crashes and display issues, and [DISPLAY_HAT_MINI](DISPLAY_HAT_MINI.md) for orientation, activity LED, and boot splash.
