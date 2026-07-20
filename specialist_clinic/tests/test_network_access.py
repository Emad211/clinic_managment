from src.common import network


class _Probe:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def connect(self, _target):
        return None

    def getsockname(self):
        return ("192.168.10.25", 50000)


def test_network_info_prioritizes_lan_and_builds_peer_urls(monkeypatch):
    monkeypatch.setattr(network.socket, "socket", lambda *_args: _Probe())
    monkeypatch.setattr(network.socket, "gethostname", lambda: "CLINIC-PC")
    monkeypatch.setattr(
        network.socket,
        "gethostbyname_ex",
        lambda _host: ("CLINIC-PC", [], ["127.0.0.1", "192.168.10.25"]),
    )
    monkeypatch.setattr(
        network.socket,
        "getaddrinfo",
        lambda *_args: [(None, None, None, None, ("10.0.0.4", 0))],
    )

    result = network.get_network_info(8090)

    assert result["hostname"] == "CLINIC-PC"
    assert result["primary_url"] == "http://10.0.0.4:8090"
    assert result["accounting_url"] == "http://10.0.0.4:8080"
    assert [item["ip"] for item in result["addresses"]] == [
        "10.0.0.4",
        "192.168.10.25",
        "127.0.0.1",
    ]


def test_network_info_falls_back_to_localhost(monkeypatch):
    class _FailedProbe(_Probe):
        def connect(self, _target):
            raise OSError

    monkeypatch.setattr(network.socket, "socket", lambda *_args: _FailedProbe())
    monkeypatch.setattr(network.socket, "gethostname", lambda: "OFFLINE-PC")
    monkeypatch.setattr(network.socket, "gethostbyname_ex", lambda _host: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(network.socket, "getaddrinfo", lambda *_args: (_ for _ in ()).throw(OSError()))

    result = network.get_network_info(8090)

    assert result["primary_url"] == "http://127.0.0.1:8090"
    assert result["addresses"][0]["is_localhost"] is True
