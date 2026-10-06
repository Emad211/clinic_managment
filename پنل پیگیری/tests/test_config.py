from __future__ import annotations

import pytest

from src.config.settings import CONFIG_FILENAME, ConfigError, load_settings


def test_first_run_creates_config_with_secret(tmp_path):
    s = load_settings(tmp_path)
    text = (tmp_path / CONFIG_FILENAME).read_text(encoding="utf-8")
    assert s.port == 8091 and s.host == "0.0.0.0" and s.open_browser
    assert (s.poll_seconds, s.read_budget_ms, s.busy_timeout_ms) == (5, 200, 250)
    assert s.accounting_db_path == ""
    assert len(s.secret_key) == 64 and s.secret_key in text
    assert load_settings(tmp_path).secret_key == s.secret_key        # stable across runs
    assert s.panel_db_path == tmp_path / "peygiri_panel.db"


def write(tmp_path, body: str, bom: bool = False) -> None:
    (tmp_path / CONFIG_FILENAME).write_text(("\ufeff" if bom else "") + body, encoding="utf-8")


BASE = """[accounting]
db_path = C:\\حسابداری سیب\\clinic_new.db   ; مسیر
[server]
host = 0.0.0.0
port = 8091
open_browser = false
allowed_clients = 127.0.0.1, 192.168.1.20
[sync]
poll_seconds = 7
read_budget_ms = BUDGET
busy_timeout_ms = BUSY
[app]
secret_key = abc
"""


def cfg(budget: int = 150, busy: int = 100) -> str:
    return BASE.replace("BUDGET", str(budget)).replace("BUSY", str(busy))


def test_reads_persian_path_inline_comments_and_bom(tmp_path):
    write(tmp_path, cfg(), bom=True)
    s = load_settings(tmp_path)
    assert s.accounting_db_path == "C:\\حسابداری سیب\\clinic_new.db"
    assert s.allowed_clients == ("127.0.0.1", "192.168.1.20")
    assert (s.poll_seconds, s.read_budget_ms, s.busy_timeout_ms, s.open_browser) == (7, 150, 100, False)


def test_safety_caps_cannot_be_raised(tmp_path):
    write(tmp_path, cfg(budget=5000, busy=9000))
    s = load_settings(tmp_path)
    assert (s.read_budget_ms, s.busy_timeout_ms) == (200, 250)


@pytest.mark.parametrize("old,new", [
    ("poll_seconds = 7", "poll_seconds = 2"), ("poll_seconds = 7", "poll_seconds = 30"),
    ("port = 8091", "port = 70000"), ("port = 8091", "port = abc"),
    ("open_browser = false", "open_browser = maybe"),
    ("192.168.1.20", "192.168.1.300"), ("read_budget_ms = 150", "read_budget_ms = 0"),
])
def test_invalid_values_are_rejected(tmp_path, old, new):
    write(tmp_path, cfg().replace(old, new))
    with pytest.raises(ConfigError):
        load_settings(tmp_path)
