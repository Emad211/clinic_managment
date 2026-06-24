"""
Management command: seed_demo

Loads a clinically representative subset of demo patients from
specialist_clinic/seed_demo_data.py FAITHFULLY into the platform Postgres DB:
  - accounting.patients
  - clinical.patient_links
  - clinical.patient_conditions  (mapped from condition ids 1–5)
  - clinical.vital_readings
  - clinical.patient_medications
  - clinical.patient_flags
  - platform.users: admin/admin (bcrypt) for demo login

Idempotent: keyed by national_id (accounting.patients) and national_id-derived
UUID for the accounting.patients.uuid column. Re-running is safe.

Demo patients seeded (faithful subset from seed_demo_data.py):
  TEST0001 — دیابت کنترل‌شده (HbA1c 7.2→6.6)
  TEST0002 — دیابت کنترل‌نشده رو‌به‌بهبود (HbA1c 9.6→7.4, bp elevated)
  TEST0003 — دیابت+فشار+CKD (complex comorbidity)
  TEST0007 — سالمند فراژیل (diabetes+hypertension, frailty=complex, hypo_risk=high)

Usage:
  python manage.py seed_demo
  python manage.py seed_demo --tenant-id 1
  python manage.py seed_demo --admin-password admin  # default admin password
"""
import json
import uuid as uuid_module
from pathlib import Path

import bcrypt
import psycopg
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


# ---------------------------------------------------------------------------
# Condition code → clinical.conditions.code (seeded by slice2)
# We query the DB at runtime to get the real PKs.
# ---------------------------------------------------------------------------
_CONDITION_CODE_MAP = {
    1: "diabetes",
    2: "hypertension",
    3: "hyperlipidemia",
    4: "ckd",
    5: "thyroid",
}

# ---------------------------------------------------------------------------
# Demo patient subset — faithful mirror of seed_demo_data.py PATIENTS
# (4 patients: controlled diabetic, uncontrolled diabetic, complex, elderly frail)
# ---------------------------------------------------------------------------

def _month_dates(y, m, count, step):
    out = []
    for _ in range(count):
        out.append(f"{y:04d}-{m:02d}-01")
        m += step
        while m > 12:
            m -= 12
            y += 1
    return out


def _trend(a, b, n):
    if n == 1:
        return [a]
    return [a + (b - a) * i / (n - 1) for i in range(n)]


D12 = _month_dates(2024, 6, 12, 2)    # every 2 months, 12 readings
D6  = _month_dates(2024, 6, 6, 4)     # quarterly-ish, 6 readings
D3  = ["2024-06-01", "2025-04-01", "2026-04-01"]   # ~annual labs, 3 readings

DEMO_PATIENTS = [
    dict(
        nid="TEST0001",
        name="نمونه", family_name="۱ - کنترل خوب",
        phone="09120000001", gender="male", birth="1975-03-10",
        conditions=[1],
        flags={},
        vitals={
            "hba1c":       (7.2, 6.6, D6),
            "fbs":         (140, 118, D12),
            "bp_systolic": (128, 124, D12),
            "bp_diastolic":(82,  78,  D12),
            "weight":      (84,  81,  D12),
        },
        meds=[
            dict(drug_name="متفورمین", drug_class="metformin",
                 dose="1000mg", schedule="روزی دو بار",
                 start_date="2024-06-15", is_active=True),
        ],
    ),
    dict(
        nid="TEST0002",
        name="نمونه", family_name="۲ - قند کنترل‌نشده",
        phone="09120000002", gender="female", birth="1968-07-22",
        conditions=[1],
        flags={"hypo_risk": "low"},
        vitals={
            "hba1c":       (9.6, 7.4, D6),
            "fbs":         (220, 140, D12),
            "bp_systolic": (134, 128, D12),
            "bp_diastolic":(86,  80,  D12),
            "weight":      (92,  86,  D12),
        },
        meds=[
            dict(drug_name="متفورمین", drug_class="metformin",
                 dose="1000mg", schedule="روزی دو بار",
                 start_date="2024-06-15", is_active=True),
            dict(drug_name="امپاگلیفلوزین", drug_class="sglt2i",
                 dose="10mg", schedule="روزانه",
                 start_date="2025-01-10", is_active=True),
        ],
    ),
    dict(
        nid="TEST0003",
        name="نمونه", family_name="۳ - دیابت+فشار+کلیه",
        phone="09120000003", gender="male", birth="1958-01-05",
        conditions=[1, 2, 4],
        flags={
            "ckd_stage_g": "G3b",
            "ckd_stage_a": "A3",
            "hypo_risk":   "atrisk",
        },
        vitals={
            "hba1c":       (8.4, 7.6, D6),
            "fbs":         (180, 150, D12),
            "bp_systolic": (158, 134, D12),
            "bp_diastolic":(94,  82,  D12),
            "egfr":        (52,  38,  D3),
            "uacr":        (180, 320, D3),
            "weight":      (88,  85,  D12),
        },
        meds=[
            dict(drug_name="متفورمین", drug_class="metformin",
                 dose="500mg", schedule="روزانه",
                 start_date="2024-06-15", is_active=True),
            dict(drug_name="لیزینوپریل", drug_class="acei",
                 dose="10mg", schedule="روزانه",
                 start_date="2024-06-15", is_active=True),
            dict(drug_name="داپاگلیفلوزین", drug_class="sglt2i",
                 dose="10mg", schedule="روزانه",
                 start_date="2024-09-01", is_active=True),
            dict(drug_name="فینرنون", drug_class="finerenone",
                 dose="10mg", schedule="روزانه",
                 start_date="2025-05-01", is_active=True),
        ],
    ),
    dict(
        nid="TEST0007",
        name="نمونه", family_name="۷ - سالمند فراژیل",
        phone="09120000007", gender="male", birth="1944-02-14",
        conditions=[1, 2],
        flags={"frailty": "complex", "hypo_risk": "high"},
        vitals={
            "hba1c":       (8.2, 7.8, D6),
            "fbs":         (160, 150, D12),
            "bp_systolic": (138, 132, D12),
            "bp_diastolic":(80,  76,  D12),
            "weight":      (70,  68,  D12),
        },
        meds=[
            dict(drug_name="لیناگلیپتین", drug_class="dpp4i",
                 dose="5mg", schedule="روزانه",
                 start_date="2024-06-15", is_active=True),
            dict(drug_name="آملودیپین", drug_class="ccb",
                 dose="5mg", schedule="روزانه",
                 start_date="2024-06-15", is_active=True),
        ],
    ),
]


def _build_conninfo(conf):
    parts = []
    for dk, pk in [("NAME", "dbname"), ("USER", "user"),
                   ("PASSWORD", "password"), ("HOST", "host"), ("PORT", "port")]:
        v = conf.get(dk)
        if v:
            parts.append(f"{pk}='{str(v).replace(chr(39), chr(92)+chr(39))}'")
    return " ".join(parts)


def _deterministic_uuid(national_id: str) -> uuid_module.UUID:
    """Stable UUID from national_id via UUID5 (namespace: DNS)."""
    return uuid_module.uuid5(uuid_module.NAMESPACE_DNS, f"demo.halqe.{national_id}")


class Command(BaseCommand):
    help = (
        "Seed demo patients (representative subset) + admin user into the "
        "halqe platform Postgres DB. Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant-id",
            type=int,
            default=1,
            help="Tenant ID to seed patients for (default: 1).",
        )
        parser.add_argument(
            "--admin-password",
            default="admin",
            help="Password for the admin user (default: 'admin').",
        )

    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        admin_password = options["admin_password"]

        db_conf = settings.DATABASES["default"]
        conninfo = _build_conninfo(db_conf)

        with psycopg.connect(conninfo, autocommit=True) as conn:
            # ── 1. Resolve condition code → DB id map ─────────────────────────
            cond_id_map: dict[str, int] = {}
            for code in _CONDITION_CODE_MAP.values():
                row = conn.execute(
                    "SELECT id FROM clinical.conditions "
                    "WHERE tenant_id=%s AND code=%s",
                    (tenant_id, code),
                ).fetchone()
                if row:
                    cond_id_map[code] = row[0]
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Condition '{code}' not found in DB for tenant={tenant_id}. "
                            "Run apply_schema first."
                        )
                    )

            # ── 2. Seed patients ──────────────────────────────────────────────
            patients_seeded = 0
            for spec in DEMO_PATIENTS:
                nid = spec["nid"]
                pat_uuid = _deterministic_uuid(nid)

                # accounting.patients — idempotent by uuid
                conn.execute(
                    """
                    INSERT INTO accounting.patients
                        (tenant_id, uuid, name, family_name, national_id,
                         phone_number, birthdate, gender)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (uuid) DO NOTHING
                    """,
                    (
                        tenant_id, pat_uuid,
                        spec["name"], spec["family_name"],
                        nid, spec["phone"],
                        spec["birth"], spec["gender"],
                    ),
                )

                row = conn.execute(
                    "SELECT id FROM accounting.patients WHERE uuid=%s",
                    (pat_uuid,),
                ).fetchone()
                patient_id = row[0]

                # clinical.patient_links — idempotent
                conn.execute(
                    """
                    INSERT INTO clinical.patient_links
                        (tenant_id, patient_id, is_active)
                    VALUES (%s, %s, TRUE)
                    ON CONFLICT (tenant_id, patient_id) DO NOTHING
                    """,
                    (tenant_id, patient_id),
                )

                link_row = conn.execute(
                    "SELECT id FROM clinical.patient_links "
                    "WHERE tenant_id=%s AND patient_id=%s",
                    (tenant_id, patient_id),
                ).fetchone()
                link_id = link_row[0]

                # patient_conditions
                for cond_num in spec["conditions"]:
                    cond_code = _CONDITION_CODE_MAP.get(cond_num)
                    if not cond_code:
                        continue
                    cond_db_id = cond_id_map.get(cond_code)
                    if not cond_db_id:
                        self.stdout.write(
                            self.style.WARNING(
                                f"    Skipping condition {cond_code} "
                                f"(not in DB) for {nid}"
                            )
                        )
                        continue
                    conn.execute(
                        """
                        INSERT INTO clinical.patient_conditions
                            (tenant_id, patient_link_id, condition_id,
                             is_active, diagnosed_at)
                        VALUES (%s, %s, %s, TRUE, now())
                        ON CONFLICT DO NOTHING
                        """,
                        (tenant_id, link_id, cond_db_id),
                    )

                # patient_flags
                for flag_key, flag_val in spec.get("flags", {}).items():
                    conn.execute(
                        """
                        INSERT INTO clinical.patient_flags
                            (tenant_id, patient_link_id, flag_key, value)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (tenant_id, patient_link_id, flag_key)
                            DO UPDATE SET value = EXCLUDED.value
                        """,
                        (tenant_id, link_id, flag_key, str(flag_val)),
                    )

                # vital_readings — we do a check-before-insert per (type, measured_at)
                # to avoid exploding duplicates on re-run. Simpler: we use the fact
                # that the readings are keyed on a specific date string at 10:00:00.
                for vtype, (start_val, end_val, dates) in spec["vitals"].items():
                    values = _trend(start_val, end_val, len(dates))
                    for dt, val in zip(dates, values):
                        measured_at = dt + " 10:00:00+03:30"
                        conn.execute(
                            """
                            INSERT INTO clinical.vital_readings
                                (tenant_id, patient_link_id, type, value,
                                 unit, measured_at, source)
                            VALUES (%s, %s, %s, %s, %s, %s, 'demo')
                            ON CONFLICT DO NOTHING
                            """,
                            (
                                tenant_id, link_id, vtype,
                                round(val, 1),
                                None,
                                measured_at,
                            ),
                        )

                # patient_medications
                for med in spec.get("meds", []):
                    conn.execute(
                        """
                        INSERT INTO clinical.patient_medications
                            (tenant_id, patient_link_id, drug_name, drug_class,
                             dose, schedule, start_date, is_active, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            tenant_id, link_id,
                            med["drug_name"], med["drug_class"],
                            med["dose"], med.get("schedule"),
                            med["start_date"], med["is_active"],
                        ),
                    )

                patients_seeded += 1
                self.stdout.write(
                    f"  {nid} → accounting.patients.id={patient_id}, "
                    f"link_id={link_id}"
                )

            # ── 3. Seed admin user ────────────────────────────────────────────
            pw_hash = bcrypt.hashpw(
                admin_password.encode(), bcrypt.gensalt()
            )
            conn.execute(
                """
                INSERT INTO platform.users
                    (tenant_id, username, password_hash, role, app,
                     is_active, failed_attempts)
                VALUES (%s, 'admin', %s, 'manager', 'platform', TRUE, 0)
                ON CONFLICT (tenant_id, username) DO UPDATE
                    SET password_hash = EXCLUDED.password_hash,
                        role          = 'manager',
                        is_active     = TRUE,
                        failed_attempts = 0,
                        locked_until  = NULL
                """,
                (tenant_id, pw_hash),
            )

            user_row = conn.execute(
                "SELECT id FROM platform.users WHERE tenant_id=%s AND username='admin'",
                (tenant_id,),
            ).fetchone()
            admin_user_id = user_row[0]

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. {patients_seeded} demo patients seeded "
                f"(tenant={tenant_id}). "
                f"Admin user id={admin_user_id} (username=admin, "
                f"password='{admin_password}')."
            )
        )
        self.stdout.write(
            self.style.NOTICE(
                "Demo patients: TEST0001 (controlled DM), TEST0002 (uncontrolled DM), "
                "TEST0003 (DM+HTN+CKD), TEST0007 (elderly frail DM+HTN)."
            )
        )
