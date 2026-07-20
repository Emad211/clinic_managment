"""Local-network discovery helpers for the settings page."""
from __future__ import annotations

import ipaddress
import socket


def _valid_ipv4(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        return address.version == 4 and not address.is_unspecified
    except ValueError:
        return False


def _local_ipv4_addresses() -> list[str]:
    """Return usable LAN addresses first and localhost as a final fallback."""
    found: set[str] = set()
    hostname = socket.gethostname()

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            # No packet is sent; connect lets the OS select the active interface.
            probe.connect(("8.8.8.8", 80))
            found.add(probe.getsockname()[0])
    except OSError:
        pass

    try:
        found.update(socket.gethostbyname_ex(hostname)[2])
    except OSError:
        pass

    try:
        found.update(
            item[4][0]
            for item in socket.getaddrinfo(hostname, None, socket.AF_INET)
        )
    except OSError:
        pass

    lan = sorted(ip for ip in found if _valid_ipv4(ip) and not ip.startswith("127."))
    return [*lan, "127.0.0.1"]


def get_network_info(port: int, accounting_port: int = 8080) -> dict:
    """Build URLs for this app and its accounting peer on the clinic LAN."""
    addresses = _local_ipv4_addresses()
    preferred_ip = next((ip for ip in addresses if not ip.startswith("127.")), addresses[0])
    return {
        "hostname": socket.gethostname(),
        "port": port,
        "addresses": [
            {
                "ip": ip,
                "is_localhost": ip.startswith("127."),
                "specialist_url": f"http://{ip}:{port}",
                "accounting_url": f"http://{ip}:{accounting_port}",
            }
            for ip in addresses
        ],
        "primary_url": f"http://{preferred_ip}:{port}",
        "accounting_url": f"http://{preferred_ip}:{accounting_port}",
    }
