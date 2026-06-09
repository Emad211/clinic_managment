"""ETL: port the FULL clinical catalogs from specialist.db into the GLOBAL
platform catalogs (clinic IS NULL).

    python manage.py etl_catalog --specialist-db ../specialist_clinic/specialist.db

Brings the real ~57 ADA rules (with complete trigger_json + recommendation +
dosage_titration + monitoring + contraindications), 13 indicators, 18 flags,
19 drug classes, 5 conditions — far more faithful than hand-rewriting them.
Idempotent (update_or_create on (clinic=NULL, code/key)). Source DB read-only.

RLS note: writes global rows (clinic_id NULL) — run under the platform owner /
BYPASSRLS ops role, not a tenant role.
"""

import json
import sqlite3

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.chronic.models import (
    ClinicalIndicator,
    ClinicalRule,
    Condition,
    DrugClass,
    FlagCatalog,
)


def _ro(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _jsonl(s, fallback):
    if not s:
        return fallback
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return fallback


def _b(v):
    return bool(v) if v is not None else False


class Command(BaseCommand):
    help = "Port full clinical catalogs from specialist.db into global platform catalogs."

    def add_arguments(self, parser):
        parser.add_argument("--specialist-db", required=True)

    @transaction.atomic
    def handle(self, *args, **o):
        try:
            con = _ro(o["specialist_db"])
        except sqlite3.Error as e:
            raise CommandError(f"cannot open specialist db: {e}")

        n = {}

        # drug_classes: class_key -> code
        c = 0
        for r in con.execute("SELECT * FROM drug_classes"):
            DrugClass.objects.update_or_create(
                clinic=None, code=r["class_key"],
                defaults={
                    "label": r["label"] or "",
                    "glucose_lowering": _b(r["glucose_lowering"]),
                    "display_order": r["display_order"] or 0,
                    "is_active": _b(r["is_active"]),
                },
            )
            c += 1
        n["drug_classes"] = c

        # conditions
        c = 0
        for r in con.execute("SELECT * FROM conditions"):
            Condition.objects.update_or_create(
                clinic=None, code=r["code"],
                defaults={"name": r["name"] or "", "is_active": _b(r["is_active"])},
            )
            c += 1
        n["conditions"] = c

        # clinical_indicators
        c = 0
        for r in con.execute("SELECT * FROM clinical_indicators"):
            ClinicalIndicator.objects.update_or_create(
                clinic=None, key=r["key"],
                defaults={
                    "label": r["label"] or "",
                    "unit": r["unit"] or "",
                    "category": r["category"] or "",
                    "direction": r["direction"] or "",
                    "warn": r["warn"],
                    "danger": r["danger"],
                    "target": r["target"] or "",
                    "goal_low": r["goal_low"],
                    "goal_high": r["goal_high"],
                    "conditions": r["conditions"] or "",
                    "risk_weight": r["risk_weight"],
                    "is_vital": _b(r["is_vital"]),
                    "display_order": r["display_order"] or 0,
                    "is_active": _b(r["is_active"]),
                    "notes": r["notes"] or "",
                },
            )
            c += 1
        n["clinical_indicators"] = c

        # flag_catalog: flag_key -> code
        c = 0
        for r in con.execute("SELECT * FROM flag_catalog"):
            FlagCatalog.objects.update_or_create(
                clinic=None, code=r["flag_key"],
                defaults={
                    "label": r["label"] or "",
                    "flag_type": r["flag_type"] or "",
                    "options": _jsonl(r["options"], {}),
                    "category": r["category"] or "",
                    "display_order": r["display_order"] or 0,
                    "is_active": _b(r["is_active"]),
                    "notes": r["notes"] or "",
                },
            )
            c += 1
        n["flag_catalog"] = c

        # clinical_rules: rule_code -> code (the 57 ADA rules)
        c = 0
        for r in con.execute("SELECT * FROM clinical_rules"):
            ClinicalRule.objects.update_or_create(
                clinic=None, code=r["rule_code"],
                defaults={
                    "title": r["title"] or "",
                    "category": r["category"] or "",
                    "trigger_json": _jsonl(r["trigger_json"], {}),
                    "human_if": r["human_if"] or "",
                    "recommendation": r["recommendation"] or "",
                    "dosage_titration": r["dosage_titration"] or "",
                    "monitoring": r["monitoring"] or "",
                    "contraindications": r["contraindications"] or "",
                    "evidence_level": r["evidence_level"] or "",
                    "action_type": r["action_type"] or "",
                    "action_params_json": _jsonl(r["action_params_json"], {}),
                    "severity": r["severity"] or "suggestion",
                    "priority": r["priority"] or 0,
                    "source_ref": r["source_ref"] or "",
                    "is_active": _b(r["is_active"]),
                    "notes": r["notes"] or "",
                },
            )
            c += 1
        n["clinical_rules"] = c

        con.close()
        self.stdout.write(self.style.SUCCESS(
            "Ported global catalogs from specialist.db: "
            f"{n['drug_classes']} drug classes, {n['conditions']} conditions, "
            f"{n['clinical_indicators']} indicators, {n['flag_catalog']} flags, "
            f"{n['clinical_rules']} clinical rules."
        ))
