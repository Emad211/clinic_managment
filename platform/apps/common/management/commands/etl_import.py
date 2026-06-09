"""ETL: import the two legacy SQLite apps into ONE platform tenant.

    python manage.py etl_import --clinic-slug main --clinic-name "درمانگاه اصلی" \
        --webapp-db ../webapp/clinic_new.db \
        --specialist-db ../specialist_clinic/specialist.db

Maps the existing data to the unified model (docs/DATA_MODEL.md §5): the whole
current dataset becomes a single ``clinic``; ``webapp.patients`` and
``specialist.patient_links`` MERGE into one ``patient`` keyed by national_id
(this retires the read-only accounting_bridge). Source DBs are opened read-only
and never written.

Scope: clinic + users (both apps) + patients (merged) + wallet balance, AND the
per-patient chronic records that feed the rule engine — vitals, medications,
conditions, flags, follow-ups (linked via patient_links.id). Run `etl_catalog`
FIRST so the global Condition/FlagCatalog/DrugClass/ClinicalIndicator catalogs
exist to link against. Source DBs are read-only; legacy timestamps are Gregorian
ISO (verified) so no Jalali conversion is needed here.

TODO (later loops): accounting rows, SMS, tariffs, allergies/labs/appointments
(currently empty in source).

RLS note: writes RLS tables. On PostgreSQL run under the platform owner /
BYPASSRLS ops role, not a tenant role.
"""

import sqlite3
from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.chronic.models import (
    ClinicalIndicator, Condition, DrugClass, FlagCatalog, FollowupTask,
    PatientCondition, PatientFlag, PatientMedication, VitalReading,
)
from apps.identity.models import AppUser, Clinic
from apps.patients.models import Patient

ROLE_MAP = {
    "manager": "clinic_manager",
    "admin": "clinic_manager",
    "clinic_manager": "clinic_manager",
    "reception": "reception",
    "doctor": "doctor",
    "nurse": "nurse",
}


def _ro(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _map_role(r):
    return ROLE_MAP.get((r or "").strip().lower(), "reception")


def _parse_date(s):
    if not s:
        return None
    s = str(s).strip().replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).date()
        except ValueError:
            continue
    return None


def _parse_dt(s):
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(s[:19], fmt)
            # stored as Tehran local; make aware in the project tz (Asia/Tehran)
            return timezone.make_aware(naive)
        except (ValueError, OverflowError):
            continue
    return None


def _split_name(full):
    parts = (full or "").strip().split(" ", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", (parts[0] if parts and parts[0] else "")


class Command(BaseCommand):
    help = "Import legacy webapp + specialist SQLite DBs into one platform tenant."

    def add_arguments(self, parser):
        parser.add_argument("--clinic-slug", required=True)
        parser.add_argument("--clinic-name", required=True)
        parser.add_argument("--webapp-db", required=True)
        parser.add_argument("--specialist-db", default=None)

    @transaction.atomic
    def handle(self, *args, **o):
        clinic, created = Clinic.objects.get_or_create(
            slug=o["clinic_slug"],
            defaults={"name": o["clinic_name"], "status": "active"},
        )
        self.stdout.write(f"Clinic {'created' if created else 'exists'} (slug={clinic.slug}, id={clinic.id})")

        try:
            wdb = _ro(o["webapp_db"])
        except sqlite3.Error as e:
            raise CommandError(f"cannot open webapp db: {e}")
        sdb = _ro(o["specialist_db"]) if o.get("specialist_db") else None

        rows_u = self._import_users(clinic, wdb, sdb)
        rows_p, link_map = self._import_patients(clinic, wdb, sdb)
        chronic = self._import_chronic(clinic, sdb, link_map) if sdb else {}

        wdb.close()
        if sdb:
            sdb.close()

        # Authoritative distinct totals (de-duped by clinic), not rows processed.
        tot_u = AppUser.objects.filter(clinic=clinic).count()
        tot_p = Patient.objects.filter(clinic=clinic).count()
        self.stdout.write(self.style.SUCCESS(
            f"Clinic {clinic.slug}: {tot_u} users ({rows_u} source rows), "
            f"{tot_p} patients ({rows_p} source rows merged by national_id)."
        ))
        if chronic:
            self.stdout.write(self.style.SUCCESS(
                "Chronic records: "
                + ", ".join(f"{v} {k}" for k, v in chronic.items())
            ))

    def _import_users(self, clinic, wdb, sdb):
        count = 0
        sources = [("webapp", wdb)]
        if sdb:
            sources.append(("specialist", sdb))
        for _label, con in sources:
            for r in con.execute("SELECT * FROM users"):
                pw = r["password_hash"]
                pw_bytes = bytes(pw) if pw is not None else b""
                AppUser.objects.update_or_create(
                    clinic=clinic,
                    username=r["username"],
                    defaults={
                        "password_hash": pw_bytes,
                        "role": _map_role(r["role"]),
                        "full_name": r["full_name"] or "",
                        "is_active": bool(r["is_active"]),
                        "failed_attempts": r["failed_attempts"] or 0,
                        "locked_until": _parse_dt(r["locked_until"]),
                        "last_login": _parse_dt(r["last_login"]),
                    },
                )
                count += 1
        return count

    def _import_patients(self, clinic, wdb, sdb):
        seen = 0
        link_map = {}  # specialist patient_links.id -> Patient (for chronic FK)
        # 1) webapp.patients — richer demographics
        for r in wdb.execute("SELECT * FROM patients"):
            nid = (r["national_id"] or "").strip() or None
            defaults = {
                "first_name": r["name"] or "",
                "last_name": r["family_name"] or "",
                "phone_number": r["phone_number"] or "",
                "gender": (r["gender"] or "").strip(),
                "birthdate": _parse_date(r["birthdate"]),
                "insurance_type": r["insurance_type"] or "",
                "insurance_expiry": _parse_date(r["insurance_expiry"]),
                "address": r["address"] or "",
                "is_foreign": bool(r["is_foreign"]),
            }
            if nid:
                Patient.objects.update_or_create(
                    clinic=clinic, national_id=nid, defaults=defaults
                )
            else:
                Patient.objects.get_or_create(
                    clinic=clinic, national_id=None,
                    first_name=defaults["first_name"], last_name=defaults["last_name"],
                    defaults=defaults,
                )
            seen += 1

        # 2) specialist.patient_links — overlay wallet/notes, create if new
        if sdb:
            for r in sdb.execute("SELECT * FROM patient_links"):
                nid = (r["national_id"] or "").strip() or None
                fn, ln = _split_name(r["full_name"])
                base = {
                    "first_name": fn,
                    "last_name": ln,
                    "phone_number": r["phone_number"] or "",
                    "gender": (r["gender"] or "").strip(),
                    "birthdate": _parse_date(r["birthdate"]),
                    "address": r["address"] or "",
                }
                if nid:
                    p, was_new = Patient.objects.get_or_create(
                        clinic=clinic, national_id=nid, defaults=base
                    )
                else:
                    p, was_new = Patient.objects.get_or_create(
                        clinic=clinic, national_id=None, first_name=fn, last_name=ln,
                        defaults=base,
                    )
                # wallet + notes come from the specialist app regardless
                p.wallet_balance = r["wallet_balance"] or 0
                if r["notes"]:
                    p.notes = r["notes"]
                p.save(update_fields=["wallet_balance", "notes", "updated_at"])
                link_map[r["id"]] = p
                if was_new:
                    seen += 1
        return seen, link_map

    def _import_chronic(self, clinic, sdb, link_map):
        """Import per-patient chronic records that feed the rule engine. Requires
        the global catalogs (etl_catalog) to resolve condition/flag/drug refs."""
        n = {}

        # catalog lookup maps (global rows)
        cond_code = {r["id"]: r["code"] for r in sdb.execute("SELECT id, code FROM conditions")}
        cond_obj = {c.code: c for c in Condition.objects.filter(clinic__isnull=True)}
        flag_obj = {f.code: f for f in FlagCatalog.objects.filter(clinic__isnull=True)}
        dclass_obj = {d.code: d for d in DrugClass.objects.filter(clinic__isnull=True)}
        ind_obj = {i.key: i for i in ClinicalIndicator.objects.filter(clinic__isnull=True)}

        def pat(link_id):
            return link_map.get(link_id)

        # vital_readings -> VitalReading
        c = 0
        for r in sdb.execute("SELECT * FROM vital_readings"):
            p = pat(r["patient_link_id"])
            if not p:
                continue
            measured = _parse_dt(r["measured_at"]) or timezone.now()
            _, was_new = VitalReading.objects.get_or_create(
                clinic=clinic, patient=p, indicator_key=r["type"], measured_at=measured,
                defaults={
                    "indicator": ind_obj.get(r["type"]),
                    "value": r["value"] or 0,
                    "source": r["source"] or "",
                },
            )
            c += was_new
        n["vitals"] = c

        # patient_medications -> PatientMedication
        c = 0
        for r in sdb.execute("SELECT * FROM patient_medications"):
            p = pat(r["patient_link_id"])
            if not p:
                continue
            _, was_new = PatientMedication.objects.get_or_create(
                clinic=clinic, patient=p, name=r["drug_name"] or "",
                start_date=_parse_date(r["start_date"]),
                defaults={
                    "drug_class": dclass_obj.get(r["drug_class"]),
                    "dose": r["dose"] or "",
                    "frequency": r["schedule"] or "",
                    "end_date": _parse_date(r["end_date"]),
                    "is_active": bool(r["is_active"]),
                },
            )
            c += was_new
        n["medications"] = c

        # patient_conditions -> PatientCondition
        c = 0
        for r in sdb.execute("SELECT * FROM patient_conditions"):
            p = pat(r["patient_link_id"])
            cond = cond_obj.get(cond_code.get(r["condition_id"]))
            if not p or not cond:
                continue
            _, was_new = PatientCondition.objects.get_or_create(
                clinic=clinic, patient=p, condition=cond,
                defaults={
                    "onset_date": _parse_date(r["onset_date"]),
                    "status": "active" if r["is_active"] else "inactive",
                    "notes": r["notes"] or "",
                },
            )
            c += was_new
        n["conditions"] = c

        # patient_flags -> PatientFlag (value-based)
        c = 0
        for r in sdb.execute("SELECT * FROM patient_flags"):
            p = pat(r["patient_link_id"])
            flag = flag_obj.get(r["flag_key"])
            if not p or not flag:
                continue
            _, _created = PatientFlag.objects.update_or_create(
                clinic=clinic, patient=p, flag=flag,
                defaults={
                    "value": r["value"] or "",
                    "is_active": True,
                    "raised_at": _parse_dt(r["updated_at"]) or timezone.now(),
                },
            )
            c += 1
        n["flags"] = c

        # followup_tasks -> FollowupTask
        c = 0
        for r in sdb.execute("SELECT * FROM followup_tasks"):
            p = pat(r["patient_link_id"])
            if not p:
                continue
            _, was_new = FollowupTask.objects.get_or_create(
                clinic=clinic, patient=p, item_key=(r["source_rule"] or "followup"),
                due_date=_parse_date(r["due_date"]),
                defaults={
                    "title": r["reason"] or "",
                    "status": r["status"] or "open",
                    "source_rule": r["source_rule"] or "",
                    "handled_at": _parse_dt(r["resolved_at"]),
                },
            )
            c += was_new
        n["followups"] = c

        return n
