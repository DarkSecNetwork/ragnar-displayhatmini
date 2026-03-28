# PiSugar 3 and Ragnar — boot / reboot stability

## Typical errors (exact messages vary by OS and `pisugar-server` build)

| Source | Example message | Meaning |
|--------|------------------|---------|
| `pisugar-server` | I2C read/write failure, `No such device`, `Remote I/O error` | Server probed the battery MCU **before** `/dev/i2c-1` or the bus was ready. |
| `pisugar-server` | `Binding rtc i2c bus=1 addr=87` then **`Poll error: I/O error: Remote I/O error (os error 121)`** every ~1s | **Persistent I2C failure:** addr **87** = **0x57** (RTC on many PiSugar boards). **Error 121** = **`EREMOTEIO`** — no chip answered on that address (wrong **PiSugar model** in config, **no PiSugar** / loose **HAT stack**, **bad cable/power**, or **address clash** with another I2C device). Not a Ragnar bug. |
| `pisugar-server` | `Address already in use` / bind failure | Rare port conflict on restart. |
| `ragnar` | `Connection refused` to `127.0.0.1` (in Python `connect_tcp`) | **Ragnar started before** `pisugar-server` accepted TCP connections. |
| `dmesg` | I2C NAK / timeout at boot | Hardware not ready yet or loose stack. |

These are **ordering / timing** issues, not Ragnar application bugs. They should not crash the kernel, but they produce **red** journal lines and can make battery/button features flaky until services settle.

## What the Ragnar installer does (when you answer **y** to PiSugar)

1. **`/etc/systemd/system/pisugar-server.service.d/10-ragnar-boot-order.conf`**  
   - `After=systemd-udev-trigger.service` so udev has created device nodes.  
   - `ExecStartPre` waits (bounded) for **`/dev/i2c-1`** before the vendor `ExecStart` runs.

2. **`ragnar.service`**  
   - `After=pisugar-server.service` and `Wants=pisugar-server.service` so the TCP server is **usually up** before Ragnar connects.  
   - Uses **`Wants`**, not **`Requires`**, so Ragnar still starts if `pisugar-server` fails.

3. **`pisugar_button.py`**  
   - Many short retries per “wave”, then a pause and repeat — handles slow `pisugar-server` after reboot without blocking the main thread.  
   - Tunable: `RAGNAR_PISUGAR_MAX_CONNECT_ATTEMPTS`, `RAGNAR_PISUGAR_RECONNECT_INTERVAL_SEC`.

## Manual fix on an already-installed Pi (no full reinstall)

```bash
sudo /home/ragnar/Ragnar/scripts/install_pisugar_boot_dropin.sh
sudo systemctl daemon-reload
sudo systemctl restart pisugar-server
```

Add Ragnar ordering if your unit file predates this:

```bash
sudo mkdir -p /etc/systemd/system/ragnar.service.d
sudo tee /etc/systemd/system/ragnar.service.d/10-after-pisugar.conf <<'EOF'
[Unit]
After=pisugar-server.service
Wants=pisugar-server.service
EOF
sudo systemctl daemon-reload
sudo systemctl restart ragnar
```

## Diagnostics

```bash
sudo /home/ragnar/Ragnar/scripts/check_pisugar.sh
sudo journalctl -u pisugar-server -b --no-pager | tail -50
sudo journalctl -u ragnar -b --no-pager | grep -i pisugar | tail -30
```

## Hardware checks

- I2C enabled: `raspi-config` → Interface Options → I2C, or `dtparam=i2c_arm=on` in `config.txt`.  
- Firm mechanical stack and adequate **5 V** supply for Pi + HAT + PiSugar.  
- Re-run vendor config if model wrong: `sudo dpkg-reconfigure pisugar-server`.

## “Remote I/O error (os error 121)” on `Binding rtc … addr=87` (your log)

What it means: `pisugar-server` is talking to **I2C bus 1**, device address **87 (0x57)** — the **RTC** path in PiSugar’s Rust core. **121** is Linux **`EREMOTEIO`** (“remote I/O error”): the I2C transaction failed (no ACK from the expected device, bus fault, or wrong address for this board).

Do this in order:

1. **Confirm hardware**  
   PiSugar seated correctly **under** the Pi (or per Pimoroni stack order), power adequate, nothing bending pins.

2. **See what’s on the bus** (Pi Zero 2 W is usually **bus 1**):  
   `sudo apt install -y i2c-tools`  
   `sudo i2cdetect -y 1`  
   You should see a device at **0x57** (shown as `57`) if the RTC is present and reachable. **Empty / `--`** at 0x57 → hardware, stacking, or wrong board.

3. **Match the model in software**  
   `sudo dpkg-reconfigure pisugar-server`  
   Pick the **exact** PiSugar revision (PiSugar 3 vs Plus vs Pro, etc.). Wrong model → wrong addresses → endless **Poll error**.

4. **If you don’t use PiSugar** (or you’re debugging the Pi alone):  
   `sudo systemctl disable --now pisugar-server`  
   Stops the spam; Ragnar can use **`Environment=RAGNAR_DISABLE_PISUGAR=1`** if you don’t need the battery UI (see TROUBLESHOOTING).

5. **Stacking with Display HAT Mini**  
   Both use GPIO; I2C is shared on the Pi. A bad seat or **two boards fighting the bus** can cause NAKs — reseat and test with **only PiSugar** first, then add the HAT per Pimoroni’s order.

After a fix, clear the log and reboot once:  
`sudo journalctl --vacuum-time=1s` (optional) · `sudo reboot` · `sudo journalctl -u pisugar-server -b --no-pager | tail -30`
