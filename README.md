## 🔧 Installation and Configuration

<p align="center">
   <img src="https://github.com/user-attachments/assets/463d32c7-f6ca-447c-b62b-f18f2429b2b2" alt="thumbnail_IMG_0546" width="130"> 
</p>

## 📚 Table of Contents

- [Prerequisites](docs/INSTALL.md#prerequisites)
- [Quick Install](docs/INSTALL.md#quick-install)
- [Manual Install](docs/INSTALL.md#manual-install)
- [Pwnagotchi Bridge](docs/INSTALL.md#pwnagotchi-bridge)
- [License](#-license)

Use Raspberry Pi Imager to install your OS  
https://www.raspberrypi.com/software/

### 📌 Prerequisites

**→ Full details:** [docs/INSTALL.md – Prerequisites](docs/INSTALL.md#prerequisites)

![image](https://github.com/user-attachments/assets/e8d276be-4cb2-474d-a74d-b5b6704d22f5)

Prerequisites for **Raspberry Pi Zero W2 (64-bit)**. Ragnar was not developed specifically for the Pi Zero W2 64-bit, but several users have reported that the installation worked perfectly.

- Raspberry Pi OS installed (64-bit, kernel 6.6, Debian 13 trixie).
- Username and hostname set to `ragnar`.
- 2.13-inch e-Paper HAT (or Display HAT Mini) connected to GPIO pins.
- **Optional:** [PiSugar UPS](https://www.pisugar.com/) for battery and hardware button support; the installer can set up `pisugar-server`.

E-Paper V2 and V4 have been tested; V1 and V3 are expected to work the same.

### ⚡ Quick Install

**→ Full details:** [docs/INSTALL.md – Quick Install](docs/INSTALL.md#quick-install)

The fastest way to install Ragnar is using the automatic installation script:

```bash
# Download and run the installer
wget https://raw.githubusercontent.com/PierreGode/Ragnar/main/install_ragnar.sh
sudo chmod +x install_ragnar.sh && sudo ./install_ragnar.sh
# Choose option 1 for automatic installation. It may take a while. Reboot at the end.
```

For Display HAT Mini, choose option **9**, then **1** (Landscape) or **2** (Portrait).

### 🧰 Manual Install

**→ Full details:** [docs/INSTALL.md – Manual Install](docs/INSTALL.md#manual-install)

Manual install includes: activating SPI & I2C, system dependencies, cloning Ragnar and installing Python deps, configuring E-Paper display type, file descriptor limits, PAM, and services (ragnar.service, kill_port_8000.sh, USB gadget). Step-by-step instructions are in the docs.

### 🐝 Pwnagotchi Bridge

**→ Full details:** [docs/INSTALL.md – Pwnagotchi Bridge](docs/INSTALL.md#pwnagotchi-bridge)

Run Ragnar and Pwnagotchi on the same SD card via a helper script and dashboard controls. Optional and disabled until you run the Pwnagotchi installer. Use the web UI (Config → Pwnagotchi Bridge) to install/repair, switch to Pwnagotchi, or return to Ragnar.

---

## 📜 License

2024 – Ragnar is distributed under the MIT License. See the [LICENSE](LICENSE) file in this repository.
