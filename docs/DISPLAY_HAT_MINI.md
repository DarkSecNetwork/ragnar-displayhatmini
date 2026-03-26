# Display HAT Mini

## Orientation (landscape vs portrait)

- **Landscape (default):** 320×240, rotation 180°.
- **Portrait (vertical):** 240×320, rotation 90°.

**During install:** When you choose option 9 (Display HAT Mini), pick **1** for Landscape or **2** for Portrait.

**How it works:**  
The physical panel is 320×240. The installer always initializes the ST7789 at **320×240** so the **full screen** is used. For portrait it reports 240×320 to Ragnar and **rotates the image in software** before sending, so there is no "1/3 static" strip and the UI fills the display.

**Change later over SSH:**  
Re-run the installer and choose orientation, or use the sed commands below to edit the generated driver and config.

Portrait:

```bash
sudo sed -i 's/"ref_width": 320/"ref_width": 240/' /home/ragnar/Ragnar/config/shared_config.json
sudo sed -i 's/"ref_height": 240/"ref_height": 320/' /home/ragnar/Ragnar/config/shared_config.json
DHAT=$(python3 -c "import waveshare_epd; print(waveshare_epd.__file__.replace('__init__.py',''))")
sudo sed -i 's/width=320,/width=240,/' "$DHAT/displayhatmini.py"
sudo sed -i 's/height=240,/height=320,/' "$DHAT/displayhatmini.py"
sudo sed -i 's/rotation=180/rotation=0/' "$DHAT/displayhatmini.py"
sudo systemctl restart ragnar
```

Landscape (revert):

```bash
sudo sed -i 's/"ref_width": 240/"ref_width": 320/' /home/ragnar/Ragnar/config/shared_config.json
sudo sed -i 's/"ref_height": 320/"ref_height": 240/' /home/ragnar/Ragnar/config/shared_config.json
DHAT=$(python3 -c "import waveshare_epd; print(waveshare_epd.__file__.replace('__init__.py',''))")
sudo sed -i 's/width=240,/width=320,/' "$DHAT/displayhatmini.py"
sudo sed -i 's/height=320,/height=240,/' "$DHAT/displayhatmini.py"
sudo sed -i 's/rotation=0,/rotation=180,/' "$DHAT/displayhatmini.py"
sudo systemctl restart ragnar
```

### UI still in landscape after choosing portrait

If you chose portrait at install but the Ragnar UI still appears in landscape (320×240), the app was reading 320×240 from `DISPLAY_PROFILES` in `shared.py`. The installer is now fixed so the displayhatmini profile uses 240×320 for portrait. **Fix:** re-run the installer and choose option **9** (Display HAT Mini) then **2** (Portrait). No need to re-clone; run `sudo ./install_ragnar.sh` from your repo and go through the prompts. Alternatively, set `ref_width`/`ref_height` to 240 and 320 in `/home/ragnar/Ragnar/config/shared_config.json` and in `shared.py` in the `DISPLAY_PROFILES` entry for `"displayhatmini"`, then restart: `sudo systemctl restart ragnar`.

### Invalid rotation 90 for 320x240

If the service fails with `ValueError: Invalid rotation 90 for 320x240 resolution`, the generated Display HAT Mini driver was using portrait (90°) with 320×240; the st7789 library only allows 0° or 180° for non-square resolutions. **Fix:** re-run the installer (it now passes 240×320 and rotation 0 for portrait), or apply the “Portrait” sed block above to the driver file so it uses `width=240`, `height=320`, and `rotation=0`.

## Activity LED (green) off while Ragnar runs

The installer adds to `/boot/firmware/config.txt` (or `/boot/config.txt`):

- `dtparam=act_led_trigger=none` — disables the green activity LED so it doesn’t blink on disk/CPU activity.

**Apply manually if you didn’t use the installer:**

```bash
# Raspberry Pi OS (Bookworm) often uses:
echo "dtparam=act_led_trigger=none" | sudo tee -a /boot/firmware/config.txt
# If that file doesn’t exist:
echo "dtparam=act_led_trigger=none" | sudo tee -a /boot/config.txt
sudo reboot
```

**Re-enable the LED:** Remove or comment out the line in the same file, then reboot.

## Buttons and settings menu

Full reference: **[Ragnar/MENU_BUTTONS.md](../Ragnar/MENU_BUTTONS.md)** (button map, env vars, code layout, troubleshooting).

When using Display HAT Mini (Pimoroni-style 4 buttons), the following mapping is used in the Ragnar UI:

| Button | Action |
|--------|--------|
| **A** | Toggle settings menu (open/close) |
| **B** | Enter / Select (short press) |
| **X** | Up (in menu) |
| **Y** | Down (in menu) |
| **Back** | Long press **B** or double-tap **B** |

The settings menu includes sections: Network (WiFi, Ethernet, Bluetooth), WiFi Attack, AI, Display (brightness, rotation, invert colors), Sound, System (device name, IP, CPU, temp), Storage, Security, Remote Access, Logging, Updates, Developer, and Power (Restart, Shutdown). Toggle items can be changed with **B** (Select); values are stored in config. Restart and Shutdown run after a short delay. **Invert Colors** toggles `screen_reversed` (display flip).

Button GPIO pins (BCM): A=5, B=6, X=16, Y=24. If your HAT uses different pins, edit `Ragnar/displayhatmini_buttons.py` and adjust `PIN_A`, `PIN_B`, `PIN_X`, `PIN_Y`.

**Startup delay:** Buttons attach after **2.5 s** by default so SPI/display init can finish first. Override with `RAGNAR_DHM_BUTTON_DELAY` (seconds, e.g. `0` for immediate).

**Disable buttons (debug):** Set `RAGNAR_SKIP_DHM_BUTTONS=1` in the systemd environment for `ragnar.service` if you need to rule out gpiozero vs display/GPIO issues.

## Boot splash and on-screen logs

On Display HAT Mini the installer runs a short splash before Ragnar: “Booting…”, “Starting Ragnar…”, “Loading…”. Then Ragnar shows “Loading Ragnar…” until the first full UI frame. After the splash, the display shows **Loading Ragnar…** and the last 6 lines of the Ragnar service log, updating every 2 s until the UI is ready, so you can see startup progress and errors on the HAT.

## Blank or wrong display

- Enable SPI: `sudo raspi-config nonint do_spi 0` then reboot.
- Test: `python3 -c "from waveshare_epd import displayhatmini; e=displayhatmini.EPD(); e.init(); e.Clear(255)"`
- If the installer didn’t run: ensure `shared.py` is patched so buffer validation is skipped for displayhatmini (re-run installer or see main README).

### PiSugar stacked — blank display

PiSugar sits on the GPIO header and shares power and sometimes I2C traffic with the Pi. A **blank Display HAT Mini** after stacking is often one of:

1. **GPIO library conflict (fixed in current installer):** An older generated `displayhatmini.py` used **RPi.GPIO** for backlight on BCM **13** while **st7789** also drives `backlight=13`, and the menu uses **gpiozero** on pins 5, 6, 16, 24. Mixing **RPi.GPIO** and **gpiozero** can leave GPIO in a bad state. **Fix:** re-run the installer so the generated driver uses **only** st7789 for backlight (no RPi.GPIO in `displayhatmini.py`):

   ```bash
   wget https://raw.githubusercontent.com/DarkSecNetwork/ragnar-displayhatmini/main/install_ragnar.sh
   sudo chmod +x install_ragnar.sh && sudo ./install_ragnar.sh
   ```

2. **Mechanical / power:** Reseat the HAT stack; use a **5 V supply** that can handle Pi + HAT + PiSugar (undersized PSU can brown out the display).

3. **Isolate buttons:** To test whether gpiozero is involved, add to `ragnar.service` under `[Service]`:

   ```ini
   Environment=RAGNAR_SKIP_DHM_BUTTONS=1
   ```

   Then `sudo systemctl daemon-reload && sudo systemctl restart ragnar`. If the picture returns, keep the new driver from (1) and remove the env var when you want the menu buttons again.
