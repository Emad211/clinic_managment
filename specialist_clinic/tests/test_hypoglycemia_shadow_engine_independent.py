"""Guard: the hypoglycemia shadow safety net is independent of the engine.

Covers fix #5. The Level-2 hypoglycemia detector (fasting glucose < 54 mg/dL)
runs inline on the vital-write path and must never be gated behind — or silenced
by — the analytical clinical engine (Engine v2). A missed hypoglycemia event is
a patient-safety false negative, so:

  * No ``hypoglycemia_shadow*`` module may import the clinical/rule engine.
  * Recording a Level-2 glucose produces a shadow CANDIDATE with the engine
    entirely absent (never even constructed), and with zero automatic
    side effects (no follow-up task, no recommendation event).
  * A normal glucose produces no candidate — the detector is precise, not noisy.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_clinical_engine_v2_followups import _patient  # noqa: E402


_SHADOW_SOURCES = sorted((ROOT / "src").rglob("hypoglycemia_shadow*.py"))
# Import lines that would couple the safety net to the analytical engine.
_ENGINE_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+.*"
    r"(clinical_engine|rule_engine|RuleEngine|analytics_service|followup_engine"
    r"|clinical_engine\.facade|\bfacade\b)",
    re.MULTILINE,
)


@pytest.fixture()
def shadow_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,  # scheduler disabled — proves the path is inline
            "DATABASE_PATH": str(tmp_path / "hypoglycemia-shadow-indep.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "hypoglycemia-shadow-independent-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def test_shadow_sources_do_not_import_the_clinical_engine():
    # The safety net must stay a pure vital-write-path detector: no analytical
    # engine, rule engine, analytics, or follow-up engine coupling at all.
    assert _SHADOW_SOURCES, "expected hypoglycemia_shadow* sources to exist"
    offenders = {}
    for path in _SHADOW_SOURCES:
        source = path.read_text(encoding="utf-8")
        hits = _ENGINE_IMPORT.findall(source)
        if hits:
            offenders[path.name] = hits
    assert not offenders, f"shadow net coupled to the engine: {offenders}"


def _candidate_count(db):
    row = db.execute(
        "SELECT COUNT(*) AS c FROM hypoglycemia_shadow_event_versions"
    ).fetchone()
    return int(row["c"] if hasattr(row, "keys") else row[0])


def _shadow_storage_exists(db):
    row = db.execute(
        "SELECT COUNT(*) AS c FROM sqlite_master "
        "WHERE type='table' AND name='hypoglycemia_shadow_event_versions'"
    ).fetchone()
    return int(row["c"] if hasattr(row, "keys") else row[0]) > 0


def test_level2_glucose_creates_candidate_with_engine_absent(shadow_app):
    from src.adapters.sqlite.core import get_db
    from src.services.hypoglycemia_shadow_glucose_ingest import (
        HypoglycemiaShadowGlucoseIngestService,
    )

    db = get_db()
    patient_id = _patient(db, national_id="HYPOINDEP001")

    # No engine object is constructed anywhere in this call.
    reading_id = HypoglycemiaShadowGlucoseIngestService().add_vital_reading(
        patient_id,
        vtype="fbs",
        value=50,
        unit="mg/dL",
        recorded_by="nurse",
    )

    assert reading_id > 0
    assert _candidate_count(db) == 1
    head = db.execute(
        """SELECT v.status FROM hypoglycemia_shadow_event_versions v
           WHERE v.version_number=1 AND v.source_record_id=?""",
        (str(reading_id),),
    ).fetchone()
    assert head is not None
    assert (head["status"] if hasattr(head, "keys") else head[0]) == "CANDIDATE"

    # Detector is suggestion/observation-only: zero automatic side effects.
    assert db.execute(
        "SELECT COUNT(*) FROM followup_tasks WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT COUNT(*) FROM clinical_recommendation_events"
    ).fetchone()[0] == 0


def test_mmol_level2_glucose_is_converted_and_flagged(shadow_app):
    from src.adapters.sqlite.core import get_db
    from src.services.hypoglycemia_shadow_glucose_ingest import (
        HypoglycemiaShadowGlucoseIngestService,
    )

    db = get_db()
    patient_id = _patient(db, national_id="HYPOINDEP002")

    # 2.9 mmol/L == 52.2 mg/dL, below the 54 mg/dL Level-2 line.
    HypoglycemiaShadowGlucoseIngestService().add_vital_reading(
        patient_id, vtype="fbs", value=2.9, unit="mmol/L", recorded_by="nurse"
    )
    assert _candidate_count(db) == 1


def test_normal_glucose_creates_no_candidate(shadow_app):
    from src.adapters.sqlite.core import get_db
    from src.services.hypoglycemia_shadow_glucose_ingest import (
        HypoglycemiaShadowGlucoseIngestService,
    )

    db = get_db()
    patient_id = _patient(db, national_id="HYPOINDEP003")

    reading_id = HypoglycemiaShadowGlucoseIngestService().add_vital_reading(
        patient_id, vtype="fbs", value=120, unit="mg/dL", recorded_by="nurse"
    )
    assert reading_id > 0
    # The ledger may not even be installed; either way there is no candidate.
    if _shadow_storage_exists(db):
        assert _candidate_count(db) == 0
