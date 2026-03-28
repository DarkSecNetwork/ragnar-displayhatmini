# Boot log on Display HAT Mini (`ragnar-display.service`)

## Why a separate service?

The panel uses **one SPI/ST7789 device**. Only **one process** can own it at a time.  
So the boot logger **cannot** run at the same time as `ragnar.service`.

**Boot order (systemd):**

1. **`ragnar-display.service`** — `Type=oneshot`, runs `ragnar_boot_display.py`:
   - **Phase 1:** scrolling **journalctl -f** for **`RAGNAR_BOOT_DISPLAY_SEC`** seconds (default **45**).
   - **Phase 2:** **RAGNAR NETWORK** screen for **`RAGNAR_NETWORK_SCREEN_SEC`** seconds (default **10**): live **interface, IPv4, gateway, DNS**, and **SSH:** `READY` / `LOCALHOST` / `OFFLINE` (from `ip`, `/etc/resolv.conf`, `ss`, `systemctl`). Refreshes twice per second so DHCP/USB can settle.
   - Then **exits** and releases the display.
2. **`ragnar.service`** — starts **after** `ragnar-display.service` completes (`After=` / `Wants=`). Then `ExecStartPre` splash + main app run; **`display.py`** continues showing **Loading…** and recent **`journalctl -u ragnar`** lines.

So you get: **early boot + systemd messages on the HAT**, then **Ragnar’s own logs** in the normal UI. If Ragnar crashes after start, those lines appear in the **Ragnar** journal and in **`display.py`**’s startup tail—not in the short boot viewer.

## Configuration

| Env (in unit) | Meaning |
|---------------|---------|
| `RAGNAR_BOOT_DISPLAY_SEC` | How long to tail the journal (default **45**). |
| `RAGNAR_NETWORK_SCREEN_SEC` | How long to show the network/SSH summary after the journal (default **10**; set **0** to skip). |
| `RAGNAR_DIR` | Ragnar tree (default `/home/ragnar/Ragnar`). |

Override:

```bash
sudo systemctl edit ragnar-display
```

```ini
[Service]
Environment=RAGNAR_BOOT_DISPLAY_SEC=60
Environment=RAGNAR_NETWORK_SCREEN_SEC=15
```

## SSH reliability (installer)

The Ragnar installer enables SSH, touches `/boot/firmware/ssh`, adds **`/etc/ssh/sshd_config.d/50-ragnar-ssh-listenall.conf`** so **`sshd` listens on all interfaces** (validates with **`sshd -t`**; falls back to IPv4-only if needed), and opens **UFW** port 22 when UFW is active. Use the on-screen **IP** and `ssh ragnar@<IP>` (or **usb0** / gadget docs) if Wi-Fi is not the active path.

## Files

| Path | Role |
|------|------|
| `/home/ragnar/Ragnar/scripts/ragnar_boot_display.py` | Journal phase + network screen. |
| `/home/ragnar/Ragnar/scripts/network_boot_facts.py` | Collects interface, IP, GW, DNS, SSH listen state. |
| `/etc/systemd/system/ragnar-display.service` | `oneshot`, `Before=ragnar.service`. |
| `/etc/systemd/system/ragnar.service` | `After=ragnar-display.service` when Display HAT Mini is installed. |

## How to test

```bash
sudo systemctl status ragnar-display.service --no-pager
sudo journalctl -u ragnar-display.service -b --no-pager
```

Manual run (holds display until timeout — stop Ragnar first to avoid EBUSY):

```bash
sudo systemctl stop ragnar
sudo RAGNAR_BOOT_DISPLAY_SEC=10 /usr/bin/python3 -OO /home/ragnar/Ragnar/scripts/ragnar_boot_display.py
```

## Install scope

Only when the installer is run with **Display HAT Mini** (option **9**).
