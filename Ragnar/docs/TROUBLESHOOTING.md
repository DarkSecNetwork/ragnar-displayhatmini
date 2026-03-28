# Troubleshooting

## Reboot / boot reliability and safe reboot

See **[REBOOT_AND_HEALTH.md](REBOOT_AND_HEALTH.md)** for `network-online.target` ordering, pre-reboot checks, and **`safe_reboot.sh`**.

## Ragnar keeps crashing

### 1. Get the crash logs

On the Pi over SSH:

```bash
# Last 100 lines (most recent at bottom)
sudo journalctl -u ragnar -n 100 --no-pager

# Follow logs in real time
sudo journalctl -u ragnar -f

# Since last boot
sudo journalctl -u ragnar -b --no-pager
```

Save the output (or the last 50 lines before the crash) so you can see the Python traceback or error message.

### 2. Common crash causes

| Symptom | Cause | Fix |
|--------|--------|-----|
| `ModuleNotFoundError` / `ImportError` | Missing Python package | `pip3 install --break-system-packages <package>` (e.g. prctl, gpiod, st7789) |
| `No such file or directory: .../passwords.txt` | Missing data files | Create under `/home/ragnar/Ragnar/data/input/dictionary/` (see [INSTALL – Step 9](INSTALL.md#step-9-data-files-if-ragnar-complains)) |
| "Network scanner not initialized" then exit | `scanning` missing from `actions.json` | Add scanning to `/home/ragnar/Ragnar/config/actions.json` or re-run installer |
| `ValueError: Invalid rotation 90 for 320x240 resolution` | Display HAT Mini portrait: st7789 rejects 90° with 320×240 | Re-run the installer (it now passes 240×320 and rotation 0 for portrait), or see [Display HAT Mini](DISPLAY_HAT_MINI.md#invalid-rotation-90-for-320x240) for a manual fix |
| "Buffer size mismatch" / EPD init fails | Display HAT Mini buffer validation | Re-run installer (it patches shared.py to skip this for displayhatmini) |
| Out of memory / killed | Pi Zero 2 W low RAM | Close other apps; ensure only one Ragnar instance; check `free -m` |
| Display / GPIO errors | SPI not enabled or wrong driver | `sudo raspi-config nonint do_spi 0` then reboot |
| Blank Display HAT Mini with **PiSugar** stacked | GPIO conflict: old driver used RPi.GPIO on backlight while buttons use gpiozero; or I2C/busy boot | Re-run [install_ragnar.sh](https://raw.githubusercontent.com/DarkSecNetwork/ragnar-displayhatmini/main/install_ragnar.sh) so `waveshare_epd/displayhatmini.py` is regenerated **without** RPi.GPIO. Optionally set `RAGNAR_SKIP_DHM_BUTTONS=1` in the service env to test display-only; see [Display HAT Mini – PiSugar](DISPLAY_HAT_MINI.md#pisugar-stacked-blank-display) |
| `Invalid wheel filename (invalid version): 'paramiko-0.9_ivysaur'` | Bad cached wheel (e.g. from Pwnagotchi) | `pip3 cache purge` then re-run installer, or run installer (it uses `--no-cache-dir`) |
| `types-flask-migrate requires Flask-SQLAlchemy>=3.0.1` | Optional type stub conflict | Harmless; installer now installs `Flask-SQLAlchemy>=3.0.1`. Ignore or `pip3 install --break-system-packages "Flask-SQLAlchemy>=3.0.1"` |

### 3. Reduce restart thrashing

If the service crashes and systemd keeps restarting it in a loop, you can temporarily slow restarts:

```bash
sudo systemctl edit ragnar.service
```

Add (in the `[Service]` section):

```ini
[Service]
RestartSec=30
StartLimitIntervalSec=300
StartLimitBurst=5
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ragnar
```

Fix the underlying error (see logs) then you can remove or reduce `RestartSec` again.

### 4. Run Ragnar manually to see errors

```bash
cd /home/ragnar/Ragnar
sudo python3 -OO Ragnar.py
```

Any traceback will print in the terminal. Fix the reported import or config issue, then start the service again: `sudo systemctl start ragnar`.

### 5. Check dependencies

```bash
cd /home/ragnar/Ragnar
python3 -c "
import sys
for m in ('shared', 'display', 'orchestrator', 'db_manager'):
    try:
        __import__(m)
        print('OK', m)
    except Exception as e:
        print('FAIL', m, e)
"
```

---

## Display is blank

- Enable SPI: `sudo raspi-config nonint do_spi 0` then reboot.
- Test display (Display HAT Mini): `python3 -c "from waveshare_epd import displayhatmini; e=displayhatmini.EPD(); e.init(); e.Clear(255)"`
- Full steps: [DISPLAY_HAT_MINI.md](DISPLAY_HAT_MINI.md).

---

## Can’t SSH after reboot

- Remove old host key: `ssh-keygen -R <pi-ip>`
- Find the Pi: router client list, or `ping ragnar.local`, or PowerShell ping sweep (see main README).

---

## Service won’t start

- Logs: `sudo journalctl -u ragnar -n 100 --no-pager`
- Ensure `/home/ragnar/Ragnar/data/input/dictionary/passwords.txt` and `users.txt` exist and `config/actions.json` includes scanning (see [INSTALL](INSTALL.md)); install `libcap-dev` and `python-prctl` if needed; then `sudo systemctl restart ragnar`.
