# Install guide

## Quick install

1. Copy `install_ragnar.sh` to the Pi (use **LF** line endings).
2. Run: `sudo ./install_ragnar.sh`
3. Choose **9** for Display HAT Mini, then **1** (Landscape) or **2** (Portrait).
4. Optionally set static IP when prompted; skip if you use DHCP.
5. Reboot when prompted if you want.

See the main [README](../README.md) for more options and troubleshooting.

## What the installer does

- Installs system packages (including libcap-dev, libgpiod for Display HAT Mini).
- Enables SPI/I2C and SSH.
- Clones [PierreGode/Ragnar](https://github.com/PierreGode/Ragnar) and applies Display HAT Mini patches.
- Creates the Display HAT Mini driver, data dirs, and `passwords.txt` / `users.txt`.
- Ensures the scanning module is in `actions.json` and patches `shared.py` so it stays.
- Optionally disables the Raspberry Pi **activity LED** (green) so it doesn’t blink while Ragnar runs.
- Creates the `ragnar` systemd service and boot splash (Display HAT Mini).

## After install

- Ragnar UI: `http://<pi-ip>:8000`
- Logs: `sudo journalctl -u ragnar -n 100 --no-pager`
- Restart: `sudo systemctl restart ragnar`
