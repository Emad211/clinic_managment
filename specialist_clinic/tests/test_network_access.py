"""LAN access tests for the Specialist Clinic server.

These tests never touch the production accounting or specialist databases and never
open a listening socket.
"""
from __future__ import annotations


class _FakeUdpSocket:
    def __init__(self):
        self.closed = False

    def connect(self, address):
        assert address == ("8.8.8.8", 80)

    def getsockname(self):
        return ("192.168.1.50", 53111)

    def close(self):
        self.closed = True


def test_discover_local_ipv4s_prefers_primary_and_deduplicates(monkeypatch):
    from src.common import network

    fake = _FakeUdpSocket()
    monkeypatch.setattr(network.socket, "socket", lambda *args, **kwargs: fake)
    monkeypatch.setattr(network.socket, "gethostname", lambda: "clinic-server")
    monkeypatch.setattr(
        network.socket,
        "gethostbyname_ex",
        lambda hostname: (hostname, [], ["192.168.1.50", "10.0.0.8", "127.0.0.1"]),
    )
    monkeypatch.setattr(
        network.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (network.socket.AF_INET, 0, 0, "", ("172.20.0.1", 0)),
            (network.socket.AF_INET, 0, 0, "", ("192.168.1.50", 0)),
        ],
    )

    ips = network.discover_local_ipv4s()

    assert fake.closed is True
    assert ips[0] == "192.168.1.50"
    assert ips.count("192.168.1.50") == 1
    assert "10.0.0.8" in ips
    assert "172.20.0.1" in ips
    assert ips[-1] == "127.0.0.1"


def test_access_urls_uses_requested_port():
    from src.common.network import access_urls

    assert access_urls(8090, ["192.168.1.10", "127.0.0.1"]) == [
        "http://192.168.1.10:8090",
        "http://127.0.0.1:8090",
    ]


def test_invalid_addresses_are_rejected():
    from src.common.network import _valid_ipv4

    assert _valid_ipv4(None) is None
    assert _valid_ipv4("not-an-ip") is None
    assert _valid_ipv4("0.0.0.0") is None
    assert _valid_ipv4("224.0.0.1") is None
    assert _valid_ipv4("192.168.2.7") == "192.168.2.7"


def test_network_page_is_manager_only_and_shows_both_apps(tmp_path, monkeypatch):
    from src.config.settings import Config
    from src.adapters.sqlite import core

    db_path = tmp_path / "specialist_network_test.db"
    monkeypatch.setattr(Config, "DATABASE_PATH", str(db_path))
    monkeypatch.setattr(Config, "ACCOUNTING_DB_PATH", str(tmp_path / "clinic_new.db"))
    core._initialized = False

    from src.app import create_app
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "network-test-secret",
        "DATABASE_PATH": str(db_path),
    })

    with app.app_context():
        core.get_db()  # bootstrap schema + default admin

    import src.api.network as network_api
    monkeypatch.setattr(
        network_api,
        "get_network_info",
        lambda port: {
            "hostname": "clinic-server",
            "port": port,
            "local_ips": ["192.168.1.50", "127.0.0.1"],
            "access_urls": ["http://192.168.1.50:8090", "http://127.0.0.1:8090"],
            "preferred_url": "http://192.168.1.50:8090",
        },
    )
    monkeypatch.setattr(network_api.accounting_bridge, "is_available", lambda: True)

    client = app.test_client()
    anonymous = client.get("/manager/network/")
    assert anonymous.status_code in (302, 303)

    login = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=True,
    )
    assert login.status_code == 200

    response = client.get("/manager/network/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "http://192.168.1.50:8090" in html
    assert "http://192.168.1.50:8080" in html
    assert "پل حسابداری متصل است" in html
    assert "New-NetFirewallRule" in html

    core._initialized = False
