"""Local-network discovery helpers for the Specialist Clinic server.

The clinic uses a single server process and browser clients on the same LAN. These
helpers only discover/display addresses; they never open sockets for listening and
never touch either SQLite database.
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Iterable


def _valid_ipv4(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        return None
    if parsed.version != 4 or parsed.is_unspecified or parsed.is_multicast:
        return None
    return str(parsed)


def _priority(ip: str) -> tuple[int, str]:
    """Prefer the active/private LAN address; keep loopback as the final fallback."""
    addr = ipaddress.ip_address(ip)
    if addr.is_loopback:
        return (90, ip)
    if ip.startswith("192.168."):
        return (10, ip)
    if ip.startswith("10."):
        return (20, ip)
    if addr.is_private and ip.startswith("172."):
        return (30, ip)
    if addr.is_private:
        return (40, ip)
    return (70, ip)


def discover_local_ipv4s() -> list[str]:
    """Return deduplicated IPv4 addresses usable by devices on the clinic LAN.

    A UDP ``connect`` is used only to ask the OS which local interface owns the
    default route; it sends no application data. Hostname/address enumeration is a
    fallback and may also surface VPN/VM adapters, so the primary-route address is
    retained first and the rest are sorted by LAN usefulness.
    """
    found: list[str] = []

    def add(value: str | None) -> None:
        ip = _valid_ipv4(value)
        if ip and ip not in found:
            found.append(ip)

    primary: str | None = None
    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        primary = sock.getsockname()[0]
        add(primary)
    except OSError:
        pass
    finally:
        if sock is not None:
            sock.close()

    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            add(ip)
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            add(info[4][0])
    except OSError:
        pass

    add("127.0.0.1")
    tail = sorted((ip for ip in found if ip != primary), key=_priority)
    return ([primary] if primary and primary in found else []) + tail


def access_urls(port: int, ips: Iterable[str] | None = None) -> list[str]:
    addresses = list(ips) if ips is not None else discover_local_ipv4s()
    return [f"http://{ip}:{int(port)}" for ip in addresses]


def get_network_info(port: int) -> dict:
    ips = discover_local_ipv4s()
    urls = access_urls(port, ips)
    preferred = next((url for ip, url in zip(ips, urls) if ip != "127.0.0.1"), urls[0] if urls else None)
    return {
        "hostname": socket.gethostname(),
        "port": int(port),
        "local_ips": ips,
        "access_urls": urls,
        "preferred_url": preferred,
    }
