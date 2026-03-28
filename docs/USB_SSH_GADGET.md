# USB Ethernet gadget — SSH from PC (Pi Zero / Zero 2 W)

## Root cause (why “static IP at install” did not give USB SSH)

The installer historically detected **only the default route interface** (usually **wlan0**) and applied your static IPv4 there via **NetworkManager** or **dhcpcd**.  

If you connect the Pi to a PC over **USB OTG** and expect **SSH on `usb0`**, you must:

1. Enable **kernel USB gadget**: **`dtoverlay=dwc2`** in `config.txt`, and **`modules-load=dwc2,g_ether`** on the **kernel cmdline** so **`g_ether`** creates **`usb0`**.
2. Assign the static address to **`usb0`**, not **wlan0**.

Without (1), **`usb0` never appears**. Without (2), the address you chose is on the wrong interface.

## What the installer does now

When you choose **static IP → interface 3 (usb0)**:

- Writes **`dtoverlay=dwc2`** to `/boot/firmware/config.txt` (and legacy `/boot/config.txt` if needed).
- Appends **`modules-load=dwc2,g_ether`** to `/boot/firmware/cmdline.txt` (or `/boot/cmdline.txt`) if missing.
- Creates a **NetworkManager** connection **`ragnar-usb-gadget`** bound to **`usb0`** with your static IPv4 (default suggestion **192.168.7.2/24**).
- If NetworkManager is not used, appends a **`usb0`** block to **`/etc/dhcpcd.conf`**.

**Reboot once** after enabling the gadget so the kernel loads **`g_ether`** and creates **`usb0`**.

## PC side (Windows)

1. Use the Pi’s **USB data** port and a **data** cable (not charge-only).
2. After the Pi boots, Device Manager should show **RNDIS** / **USB Ethernet**.
3. Set the PC’s USB NIC to the **same /24** as the Pi (e.g. Pi **192.168.7.2**, PC **192.168.7.1**, netmask **255.255.255.0**).
4. SSH: `ssh ragnar@192.168.7.2` (or whatever static you set).

## Validation on the Pi

```bash
sudo /home/ragnar/Ragnar/scripts/check_usb_ssh.sh
```

Optional expected IP override:

```bash
sudo RAGNAR_USB_EXPECT_IP=192.168.7.2 /home/ragnar/Ragnar/scripts/check_usb_ssh.sh
```

## Diagnosis commands (from your checklist)

```bash
hostname -I
ip a
ip route
lsmod | grep -E 'dwc2|g_ether'
systemctl status ssh sshd --no-pager
ss -tulpn | grep ':22'
journalctl -b | grep -iE 'usb|dwc2|g_ether|rndis|ecm'
dmesg | grep -iE 'usb|dwc2|g_ether|rndis|ecm'
```

## Files touched by the installer (USB path)

| File | Role |
|------|------|
| `/boot/firmware/config.txt` | `dtoverlay=dwc2` |
| `/boot/firmware/cmdline.txt` | `modules-load=dwc2,g_ether` |
| NetworkManager | connection `ragnar-usb-gadget` → `usb0` |
| `/etc/dhcpcd.conf` | fallback `interface usb0` block if no NM |

## Related

- [REBOOT_AND_HEALTH.md](REBOOT_AND_HEALTH.md) — boot ordering and safe reboot.
- [INSTALL.md](INSTALL.md) — full installer flow.
