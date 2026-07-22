"""Durable, settings-backed governance state for Clinical Engine v2 rollout."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.adapters.sqlite.core import get_db


_PREFIX = "clinical_engine_v2_activation_"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def report_core(report: dict) -> dict:
    """Reconstruct the immutable portion covered by ``report_hash``."""
    return {
        "schema_version": report.get("schema_version"),
        "as_of_at": report.get("as_of_at"),
        "cohort": report.get("cohort"),
        "ruleset": report.get("ruleset"),
        "patients": [
            {key: value for key, value in row.items() if key != "v2_run_id"}
            for row in (report.get("patients") or [])
        ],
        "failures": report.get("failures"),
        "checks": report.get("checks"),
    }


def valid_report(report: Any) -> bool:
    return bool(
        isinstance(report, dict)
        and report.get("status") == "PASS"
        and report.get("checks")
        and all(report["checks"].values())
        and report.get("report_hash") == content_hash(report_core(report))
    )


class ClinicalEngineActivationRepository:
    """Store activation evidence without adding mutable clinical tables.

    Settings are deliberately namespaced.  Reports and approvals remain in the
    database after rollback, while the activation seal is revoked immediately.
    """

    def _key(self, name: str) -> str:
        return _PREFIX + name

    def get_json(self, name: str, default=None):
        row = get_db().execute("SELECT value FROM settings WHERE key=?", (self._key(name),)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, ValueError):
            return default

    def put_json(self, name: str, value: Any) -> None:
        payload = canonical_json(value)
        with get_db() as db:
            db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (self._key(name), payload),
            )

    def delete(self, name: str) -> None:
        with get_db() as db:
            db.execute("DELETE FROM settings WHERE key=?", (self._key(name),))

    def raw_mode(self) -> str:
        row = get_db().execute(
            "SELECT value FROM settings WHERE key='clinical_engine_v2_mode'"
        ).fetchone()
        return str(row["value"] if row else "off").strip().lower()

    def set_raw_mode(self, mode: str) -> None:
        with get_db() as db:
            db.execute(
                "INSERT INTO settings (key, value) VALUES ('clinical_engine_v2_mode', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (mode,)
            )

    def demo_patients(self) -> list[dict]:
        ids = [f"TEST{i:04d}" for i in range(1, 11)]
        marks = ",".join("?" for _ in ids)
        rows = get_db().execute(
            f"SELECT id, national_id, full_name FROM patient_links "
            f"WHERE upper(trim(national_id)) IN ({marks}) ORDER BY national_id", ids,
        ).fetchall()
        return [dict(row) for row in rows]

    def ruleset_state(self, ruleset_id: int) -> dict | None:
        row = get_db().execute(
            "SELECT id, ruleset_code, version, content_hash, status FROM clinical_rulesets WHERE id=?",
            (ruleset_id,),
        ).fetchone()
        return dict(row) if row else None

    def valid_seal(self, mode: str) -> bool:
        seal = self.get_json("seal")
        if not isinstance(seal, dict) or seal.get("mode") != mode:
            return False
        supplied = seal.get("seal_hash")
        body = {key: value for key, value in seal.items() if key != "seal_hash"}
        if not supplied or supplied != content_hash(body):
            return False
        report = self.get_json("last_report")
        if not valid_report(report) or report["report_hash"] != seal.get("report_hash"):
            return False
        for role in ("clinical", "technical"):
            approval = self.get_json(f"approval_{role}")
            if not isinstance(approval, dict) or approval.get("report_hash") != report["report_hash"]:
                return False
        ruleset = self.ruleset_state(int(seal.get("ruleset_id") or 0))
        allowed = {"SILENT", "ACTIVE"} if mode == "on_selected" else {"ACTIVE"}
        return bool(ruleset and ruleset["status"] in allowed)
