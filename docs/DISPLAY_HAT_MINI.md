# Display HAT Mini

## Orientation (landscape vs portrait)

- **Landscape (default):** 320×240, rotation 180°.
- **Portrait (vertical):** 240×320, rotation 90°.

**During install:** When you choose option 9 (Display HAT Mini), pick **1** for Landscape or **2** for Portrait.

**Change later over SSH:**  
The st7789 driver only allows rotation 0 or 180; for portrait the driver must use **240×320** and rotation **0** (not 90). Use the sed commands below, or re-run the installer and pick the desired orientation.

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

## Boot splash

On Display HAT Mini the installer runs a short splash before Ragnar: “Booting…”, “Starting Ragnar…”, “Loading…”. Then Ragnar shows “Loading Ragnar…” until the first full UI frame. This avoids a black screen during the long startup.

## Blank or wrong display

- Enable SPI: `sudo raspi-config nonint do_spi 0` then reboot.
- Test: `python3 -c "from waveshare_epd import displayhatmini; e=displayhatmini.EPD(); e.init(); e.Clear(255)"`
- If the installer didn’t run: ensure `shared.py` is patched so buffer validation is skipped for displayhatmini (re-run installer or see main README).
