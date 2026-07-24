"""Descriptive per-patient analytics.

This service prepares measurements, timestamps, numerical deltas and administrative
counts. It deliberately does not evaluate thresholds, assign clinical risk/control
labels, declare treatment targets, or recommend an action. Those outputs belong only
to the governed Clinical Engine v2.
"""
from datetime import datetime, timedelta

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.vitals_repo import VitalsRepository
from src.adapters.sqlite.patients_repo import PatientRepository
from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.adapters.sqlite.wallet_repo import WalletRepository
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.adapters.sqlite.clinical_rules_repo import (
    ClinicalRulesRepository,
    CATEGORY_LABELS,
)
from src.adapters import accounting_bridge
from src.common.utils import format_jalali_date

_CATEGORY_ORDER = ["glycemic", "bp", "lipid", "kidney", "anthro", "other"]


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _mean(values):
    return round(sum(values) / len(values), 1) if values else None


class AnalyticsService:
    def __init__(self):
        self.vitals = VitalsRepository()
        self.patients = PatientRepository()
        # This repository is used only as descriptive catalog metadata here:
        # labels, units, categories and disease applicability. Threshold fields are
        # intentionally ignored.
        self.rules = ClinicalRulesRepository()

    def patient_analytics(self, pid: int) -> dict:
        patient = self.patients.get_by_id(pid)
        if not patient:
            return {"patient": None}

        conditions = self.patients.get_patient_conditions(pid)
        condition_codes = [
            condition.get("condition_code")
            for condition in conditions
            if condition.get("condition_code")
        ]
        indicators_meta = self.rules.for_conditions(condition_codes)

        indicators: list[dict] = []
        charts: dict[str, dict] = {}
        for meta in indicators_meta:
            key = meta["key"]
            readings = self.vitals.get_readings_canonical(pid, key, limit=200)
            latest = readings[-1] if readings else None
            previous = readings[-2] if len(readings) > 1 else None
            delta = (
                latest["value"] - previous["value"]
                if latest and previous
                else None
            )
            indicator = {
                "key": key,
                "label": meta["label"],
                "unit": meta["unit"],
                "category": meta["category"],
                "category_label": CATEGORY_LABELS.get(
                    meta["category"], meta["category"]
                ),
                "conditions": meta.get("conditions"),
                "latest": latest["value"] if latest else None,
                "previous": previous["value"] if previous else None,
                "delta": round(delta, 1) if delta is not None else None,
                "count": len(readings),
                "last_date": (
                    format_jalali_date(latest["measured_at"])
                    if latest
                    else None
                ),
            }
            indicators.append(indicator)
            if readings:
                charts[key] = {
                    "label": meta["label"],
                    "unit": meta["unit"],
                    "category": meta["category"],
                    "labels": [
                        format_jalali_date(reading["measured_at"])
                        for reading in readings
                    ],
                    "dates": [
                        str(reading["measured_at"])[:10]
                        for reading in readings
                    ],
                    "values": [reading["value"] for reading in readings],
                }

        medication_events = self.patients.get_medication_events(pid)
        event_payload = [
            {
                "drug_name": event["drug_name"],
                "event_type": event["event_type"],
                "dose": event["dose"],
                "date": (
                    str(event["event_date"])[:10]
                    if event["event_date"]
                    else None
                ),
                "date_fa": format_jalali_date(event["event_date"]),
            }
            for event in medication_events
        ]

        medications = self.patients.get_medications(pid, active_only=False)
        db = get_db()
        refill_due = db.execute(
            """SELECT COUNT(*) AS count
               FROM patient_medications
               WHERE patient_link_id=? AND is_active=1
                 AND refill_due_date IS NOT NULL
                 AND refill_due_date <= date(
                     'now','+3 hours','+30 minutes','+7 days'
                 )""",
            (pid,),
        ).fetchone()["count"]

        appointments = AppointmentRepository().list_for_patient(pid)
        done = sum(1 for item in appointments if item["status"] == "done")
        no_show = sum(
            1 for item in appointments if item["status"] == "no_show"
        )
        upcoming = [
            item for item in appointments if item["status"] == "scheduled"
        ]

        visits = []
        if patient.get("accounting_patient_id"):
            visits = accounting_bridge.get_visit_history(
                patient["accounting_patient_id"], limit=100
            )
        followups = [
            item
            for item in FollowupRepository().list_for_patient(pid)
            if item["status"] == "open"
        ]

        return {
            "patient": patient,
            "indicators": indicators,
            "by_category": self._group_by_category(indicators),
            "charts": charts,
            "med_events": event_payload,
            "conditions": conditions,
            "allergies": self.patients.get_allergies(pid),
            "medications": medications,
            "refill_due": refill_due,
            "appointments": {
                "done": done,
                "no_show": no_show,
                "upcoming": upcoming,
                "total": len(appointments),
            },
            "visits_count": len(visits),
            "last_visit": (
                format_jalali_date(visits[0]["visit_date"])
                if visits
                else None
            ),
            "per_disease": self._per_disease(conditions, indicators),
            "followups": followups,
            "wallet_balance": WalletRepository().get_balance(pid),
            "projection_policy": "DESCRIPTIVE_ONLY",
        }

    @staticmethod
    def _group_by_category(indicators) -> list[dict]:
        groups: dict[str, dict] = {}
        for indicator in indicators:
            group = groups.setdefault(
                indicator["category"],
                {
                    "category": indicator["category"],
                    "label": CATEGORY_LABELS.get(
                        indicator["category"], indicator["category"]
                    ),
                    "indicators": [],
                },
            )
            group["indicators"].append(indicator)
        return [groups[key] for key in _CATEGORY_ORDER if key in groups] + [
            group
            for key, group in groups.items()
            if key not in _CATEGORY_ORDER
        ]

    @staticmethod
    def _per_disease(conditions, indicators) -> list[dict]:
        """Group available measurements by diagnosis without grading control/risk."""
        result = []
        for condition in conditions:
            code = condition.get("condition_code")
            if not code:
                continue
            applicable = []
            for indicator in indicators:
                if indicator.get("latest") is None:
                    continue
                raw = indicator.get("conditions") or ""
                codes = {
                    part.strip()
                    for part in raw.split(",")
                    if part.strip()
                }
                if raw == "all" or code in codes:
                    applicable.append(indicator)
            result.append(
                {
                    "condition_code": code,
                    "condition_name": (
                        condition.get("condition_name") or code
                    ),
                    "indicators": applicable,
                }
            )
        return result

    def medication_effect(
        self,
        pid: int,
        med_id: int,
        indicator_key: str,
        window_days: int = 90,
    ) -> dict:
        """Return a before/after numerical comparison without causal interpretation."""
        medication = self.patients.get_medication(med_id) if med_id else None
        if not medication or not indicator_key:
            return {"ok": False, "error": "invalid"}
        start = _parse_date(medication.get("start_date"))
        if not start:
            return {"ok": False, "error": "no_start_date"}
        window_days = max(7, min(int(window_days or 90), 730))
        pre_from = start - timedelta(days=window_days)
        post_to = start + timedelta(days=window_days)

        readings = self.vitals.get_readings_canonical(
            pid, indicator_key, limit=500
        )
        pre_values, post_values = [], []
        for reading in readings:
            measured = _parse_date(reading["measured_at"])
            if not measured:
                continue
            if pre_from <= measured < start:
                pre_values.append(reading["value"])
            elif start <= measured <= post_to:
                post_values.append(reading["value"])

        pre = _mean(pre_values)
        post = _mean(post_values)
        delta = (
            round(post - pre, 1)
            if pre is not None and post is not None
            else None
        )
        meta = self.rules.get(indicator_key) or {}
        return {
            "ok": True,
            "drug_name": medication["drug_name"],
            "indicator": meta.get("label", indicator_key),
            "unit": meta.get("unit", ""),
            "pre": pre,
            "post": post,
            "delta": delta,
            "n_pre": len(pre_values),
            "n_post": len(post_values),
            "window_days": window_days,
            "start_fa": format_jalali_date(medication.get("start_date")),
            "projection_policy": "DESCRIPTIVE_ONLY",
        }
