#!/usr/bin/env python3
"""
Collect live network + SSH facts for the Display HAT Mini post-boot screen.
No hardcoded IPs — uses ip(8), hostname, /etc/resolv.conf, ss/systemctl.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


@dataclass
class NetworkFacts:
    interface: str  # e.g. wlan0, usb0, or "—"
    ip_addr: str
    gateway: str
    dns: str
    ssh_status: str  # READY | LOCALHOST | OFFLINE | ?
    detail: str  # short debug line for logs


def _run(cmd: list[str], timeout: float = 3.0) -> str:
    try:
        return subprocess.check_output(cmd, text=True, timeout=timeout, stderr=subprocess.DEVNULL)
    except Exception:
        return ""


def _default_route() -> tuple[str | None, str | None]:
    """Return (iface, gateway_ipv4) from default route."""
    out = _run(["ip", "-4", "route", "show", "default"])
    for line in out.strip().splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "default" and parts[1] == "via":
            gw = parts[2]
            iface = None
            if "dev" in parts:
                iface = parts[parts.index("dev") + 1]
            return iface, gw
    return None, None


def _ipv4_for_iface(iface: str | None) -> str | None:
    if not iface:
        return None
    out = _run(["ip", "-4", "-o", "addr", "show", "dev", iface])
    m = re.search(r"inet\s+([\d.]+)", out)
    return m.group(1) if m else None


def _hostname_first_ip() -> tuple[str | None, str | None]:
    """First non-loopback IP from hostname -I, with best-effort iface name."""
    out = _run(["hostname", "-I"]).strip().split()
    for ip in out:
        if ip.startswith("127."):
            continue
        # iface for this address
        out2 = _run(["ip", "-o", "-4", "addr"])
        for line in out2.splitlines():
            if f"inet {ip}/" in line or f"inet {ip} " in line:
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1].rstrip(":"), ip
        return None, ip
    return None, None


def _read_dns() -> str:
    servers: list[str] = []
    try:
        with open("/etc/resolv.conf", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("nameserver"):
                    parts = line.split()
                    if len(parts) >= 2 and not parts[1].startswith("127."):
                        servers.append(parts[1])
    except OSError:
        pass
    if not servers:
        return "—"
    return ", ".join(servers[:3])


def _ssh_listen_status() -> str:
    out = _run(["ss", "-tln"])
    if ":22" not in out:
        st = (_run(["systemctl", "is-active", "ssh"]) or _run(["systemctl", "is-active", "sshd"])).strip()
        return "OFFLINE" if st != "active" else "?"
    # Listening on all interfaces
    if re.search(r"(0\.0\.0\.0|\*):22\s", out) or "[::]:22" in out:
        return "READY"
    # Loopback-only
    if "127.0.0.1:22" in out or re.search(r"::1:22\s", out):
        return "LOCALHOST"
    return "READY"


def collect_network_facts() -> NetworkFacts:
    iface, gw = _default_route()
    ip = _ipv4_for_iface(iface)

    if not ip:
        iface2, ip2 = _hostname_first_ip()
        if ip2:
            iface = iface or iface2 or "?"
            ip = ip2
            if not gw:
                gw = "—"

    if not ip:
        return NetworkFacts(
            interface="—",
            ip_addr="NO NETWORK",
            gateway="—",
            dns=_read_dns(),
            ssh_status=_ssh_listen_status(),
            detail="no IPv4; no default route",
        )

    if not iface:
        iface = "?"

    if not gw:
        gw = "—"

    dns = _read_dns()
    ssh = _ssh_listen_status()
    detail = f"if={iface} ip={ip} gw={gw} ssh={ssh}"
    return NetworkFacts(
        interface=iface,
        ip_addr=ip,
        gateway=gw,
        dns=dns,
        ssh_status=ssh,
        detail=detail,
    )
