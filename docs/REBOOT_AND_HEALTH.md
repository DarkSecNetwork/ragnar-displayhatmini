# Reboot safety, health checks, and boot hardening

This document describes why Ragnar can differ **manually vs systemd**, what was hardened in the installer, and how to use **pre-reboot validation** so a bad state never triggers a blind reboot.

## Root causes addressed (evidence-based)

| Issue | Evidence | Mitigation |
|--------|-----------|------------|
| **Wi-Fi / IP not ready at service start** | `After=network.target` does not wait for DHCP; orchestrator/display race with NM. | `After=` + `Wants=network-online.target`; enable `NetworkManager-wait-online.service` when present. |
| **Static IP ignored (Bookworm)** | Only `dhcpcd.conf` written while **NetworkManager** owns `wlan0`. | Installer uses **`nmcli`** when NM is active (see `install_ragnar.sh` `configure_static_ip`). |
| **GPIO / display busy in verifier** | Second `EPD().init()` while `ragnar.service` holds lines → `EBUSY`. | Verifier treats busy as skip; self-test avoids display init unless `RAGNAR_SELFTEST_DISPLAY_INIT=1`. |
| **Menu buttons dead** | `st7789` uses **gpiodevice**; gpiozero default backend wrong on Bookworm. | `RAGNAR_GPIOZERO_FACTORY=lgpio`, `python3-lgpio`, `gpiozero>=2.0`. |
| **Installer `reboot` prompt** | Immediate reboot after long install skips validation. | Installer calls **`safe_reboot.sh`** when executable. |

## Manual run vs `systemd` run

| Factor | Manual (`sudo python3 -OO Ragnar.py`) | `systemd` |
|--------|----------------------------------------|-----------|
| **CWD** | Whatever shell CWD is | `WorkingDirectory=/home/ragnar/Ragnar` |
| **Environment** | Shell profile | Only variables set in `ragnar.service` (e.g. `RAGNAR_GPIOZERO_FACTORY`, `RAGNAR_DHM_BUTTON_DELAY`) |
| **Network** | Usually already up | May start earlier without `network-online` ordering |
| **User** | Often your user | `User=root` in installer |

If something works manually but not at boot, compare: `systemctl show ragnar -p Environment`, `journalctl -u ragnar -b`, and working directory.

## Scripts (absolute paths on Pi)

| Script | Purpose |
|--------|---------|
| `/home/ragnar/Ragnar/scripts/pre_reboot_check.sh` | Validates disk, configs, Python self-test, systemd unit, service state, network presence, SPI if Display HAT Mini. **Exits non-zero** on failure. |
| `/home/ragnar/Ragnar/scripts/safe_reboot.sh` | Runs `pre_reboot_check.sh`; only then **`/sbin/reboot`**. |
| `/home/ragnar/Ragnar/scripts/ragnar_startup_selftest.py` | Syntax + key imports + config JSON + optional display init (see env below). |

**Log file:** `/var/log/ragnar_health.log` (timestamped lines for each check and for safe reboot attempts).

## Usage

```bash
# Self-test only (safe while ragnar is running; no display GPIO by default)
sudo RAGNAR_DIR=/home/ragnar/Ragnar /usr/bin/python3 /home/ragnar/Ragnar/scripts/ragnar_startup_selftest.py

# Pre-reboot checks (does not reboot)
sudo /home/ragnar/Ragnar/scripts/pre_reboot_check.sh

# Validated reboot
sudo /home/ragnar/Ragnar/scripts/safe_reboot.sh
```

**Optional:** force display init in self-test (stop `ragnar` first or expect EBUSY):

```bash
sudo RAGNAR_SELFTEST_DISPLAY_INIT=1 RAGNAR_DIR=/home/ragnar/Ragnar /usr/bin/python3 /home/ragnar/Ragnar/scripts/ragnar_startup_selftest.py
```

**Menu:** **Restart** in the Display HAT Mini settings menu uses **`safe_reboot.sh`** when installed and executable.

## systemd unit highlights

The installer writes `/etc/systemd/system/ragnar.service` with:

- `After=network-online.target network.target ssh.service`
- `Wants=network-online.target`
- `StartLimitIntervalSec=300` / `StartLimitBurst=5`
- Absolute `ExecStart` / `WorkingDirectory`
- `Restart=always`, `RestartSec=10`

## How to test

1. **Normal service:** `sudo systemctl restart ragnar` → `systemctl status ragnar` → `journalctl -u ragnar -f`
2. **Self-test:** command above; expect `OK: ragnar_startup_selftest passed`
3. **Safe reboot:** `sudo /home/ragnar/Ragnar/scripts/safe_reboot.sh` (should reboot if all green)
4. **Failure path:** `sudo systemctl stop ragnar` → mark service failed if needed → `sudo /home/ragnar/Ragnar/scripts/pre_reboot_check.sh` → should **fail** on service state; `safe_reboot.sh` must **not** reboot

## Further diagnosis (on device)

```bash
sudo journalctl -b -p err --no-pager | tail -80
sudo journalctl -u ragnar -b --no-pager | tail -120
systemd-analyze critical-chain ragnar.service
```

See also [TROUBLESHOOTING.md](TROUBLESHOOTING.md) and [MENU_BUTTONS.md](../Ragnar/MENU_BUTTONS.md).
