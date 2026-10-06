"""Local development environment with SYNTHETIC data only.

    .venv\\Scripts\\python.exe scripts\\dev_env.py      # (re)build build/dev and write config.ini
    .venv\\Scripts\\python.exe start.py                # http://127.0.0.1:18091

Creates build/dev/clinic_new.db (fake accounting, production DDL), accounting
users reza/reza-pass (reception) and boss/boss-pass (manager), and a few of
today's visits. Doctor accounts are created by the manager in the UI, or with
--doctors (dr.alef, dr.boss — director — both password doctor-pass).
Never point this at a real clinic file.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import bcrypt  # noqa: E402

from accounting_factory import BP_CHECK_ID, BS_TEST_ID, Reception, build_accounting_db  # noqa: E402
from src.common import iran_time  # noqa: E402

DEV = ROOT / "build" / "dev"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")       # Persian paths on a cp1252 console
    ap = argparse.ArgumentParser()
    ap.add_argument("--doctors", action="store_true", help="also create doctor accounts in the panel DB")
    args = ap.parse_args()

    DEV.mkdir(parents=True, exist_ok=True)
    acc = DEV / "clinic_new.db"
    for p in (acc, ROOT / "peygiri_panel.db", ROOT / "peygiri_panel.db-wal", ROOT / "peygiri_panel.db-shm"):
        p.unlink(missing_ok=True)
    build_accounting_db(acc, invoices=60, open_invoices=0)
    rec = Reception(acc)
    h = lambda pw: bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=6))  # noqa: E731
    rec.add_user("reza", h("reza-pass"), "reception", full_name="رضا (پذیرش)")
    rec.add_user("boss", h("boss-pass"), "manager", full_name="مدیر درمانگاه")
    today = iran_time.today_str()
    rec.start_shift(2, "morning", today, f"{today} 07:30:00")

    def visit(name, family, nid, phone, at, extra=None, doctor=1):
        iid = rec.open_invoice(rec.add_patient(name, family, nid, phone), today, "morning")
        rec.add_visit(iid, doctor_id=doctor, at=f"{today} {at}")
        if extra:
            extra(iid)
    visit("مریم", "احمدی", "0499370899", "09121234567", "08:10:00",
          lambda i: rec.add_injection(i, BS_TEST_ID, "تست قند"))
    visit("خ", "حسینی", None, None, "08:25:00")
    visit("علی", "رضایی", "2170415981", "09351112233", "08:40:00",
          lambda i: rec.add_procedure(i, "کشیدن بخیه"))
    for nid, service, name in (("2110530979", BP_CHECK_ID, "کنترل فشار"), (None, BS_TEST_ID, "تست قند")):
        iid = rec.open_invoice(rec.add_patient("زهرا" if nid else "ا", "کاظمی", nid, "09125556677"), today, "morning")
        rec.add_injection(iid, service, name)

    (ROOT / "config.ini").write_text(
        "[accounting]\n"
        f"db_path = {acc}\n"
        "[server]\nhost = 127.0.0.1\nport = 18091\nopen_browser = false\n"
        "[sync]\npoll_seconds = 5\n", encoding="utf-8")
    print(f"synthetic accounting: {acc}\nconfig.ini written (port 18091)")

    if args.doctors:
        from src.adapters.accounting.bridge import AccountingBridge
        from src.adapters.sqlite import core
        from src.config.settings import load_settings
        from src.services.auth import create_doctor
        from src.services.bridge_monitor import BridgeMonitor
        from src.sync.poller import Poller
        s = load_settings(ROOT)
        core.init_db(s.panel_db_path, s.backups_dir)
        bridge = AccountingBridge(str(acc), budget_ms=200, busy_timeout_ms=250)
        BridgeMonitor(bridge).check_now()
        Poller(bridge, s.panel_db_path, interval_seconds=5).step()
        conn = core.connect(s.panel_db_path)
        for user, staff, director in (("dr.alef", 1, False), ("dr.boss", 2, True)):
            create_doctor(conn, bridge, username=user, password="doctor-pass", staff_id=staff,
                          is_director=director, actor="dev:seed", now=iran_time.now())
        conn.close()
        print("doctors: dr.alef, dr.boss (director) / doctor-pass")


if __name__ == "__main__":
    main()
