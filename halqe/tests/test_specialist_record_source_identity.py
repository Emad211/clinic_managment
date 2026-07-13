"""Source-identity continuity guards for the specialist historical importer."""
from __future__ import annotations

from pathlib import Path
import sqlite3

from django.db import connection
import pytest

from clinical.specialist_record_import import (
    ImportConflictError,
    SpecialistRecordImporter,
)
from platform_core.tenant_context import set_tenant_guc


def _source(
    path: Path,
    *,
    source_patient_id: int,
    accounting_patient_id: int,
    history_id: int | None,
) -> Path:
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE patient_links (
            id INTEGER PRIMARY KEY,
            accounting_patient_id INTEGER,
            national_id TEXT,
            full_name TEXT,
            wallet_balance INTEGER DEFAULT 0,
            sms_opt_out INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE medical_history (
            id INTEGER PRIMARY KEY,
            patient_link_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            note TEXT,
            since TEXT,
            created_at TEXT
        );
        """
    )
    db.execute(
        """
        INSERT INTO patient_links
            (id, accounting_patient_id, national_id, full_name,
             wallet_balance, sms_opt_out, is_active)
        VALUES (?, ?, NULL, 'بیمار تست continuity', 0, 0, 1)
        """,
        [source_patient_id, accounting_patient_id],
    )
    if history_id is not None:
        db.execute(
            """
            INSERT INTO medical_history
                (id, patient_link_id, title, note, since, created_at)
            VALUES (?, ?, 'سابقه continuity', 'شرح', '2020-01-01',
                    '2025-01-01 10:00:00')
            """,
            [history_id, source_patient_id],
        )
    db.commit()
    db.close()
    return path


def _count(query: str, params: list[object]) -> int:
    set_tenant_guc(1)
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        return int(cursor.fetchone()[0])


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_truncated_snapshot_is_rejected_without_changing_prior_import(
    seed_data,
    tmp_path,
):
    source = _source(
        tmp_path / "monotonic-source.db",
        source_patient_id=1,
        accounting_patient_id=seed_data["patient_id"],
        history_id=10,
    )
    kwargs = {
        "sqlite_path": source,
        "source_id": "source-continuity-truncated",
        "tenant_id": 1,
        "apply": True,
    }
    SpecialistRecordImporter(**kwargs).run()

    target_before = _count(
        """
        SELECT COUNT(*) FROM clinical.medical_history
        WHERE tenant_id=1 AND patient_link_id=%s AND title='سابقه continuity'
        """,
        [seed_data["link_id"]],
    )
    ledger_before = _count(
        """
        SELECT COUNT(*) FROM clinical.record_import_ledger
        WHERE tenant_id=1 AND source_id='source-continuity-truncated'
        """,
        [],
    )
    assert target_before == 1
    assert ledger_before == 2

    db = sqlite3.connect(source)
    db.execute("DELETE FROM medical_history WHERE id=10")
    db.commit()
    db.close()

    with pytest.raises(ImportConflictError, match=r"medical_history#10"):
        SpecialistRecordImporter(**kwargs).run()

    assert _count(
        """
        SELECT COUNT(*) FROM clinical.medical_history
        WHERE tenant_id=1 AND patient_link_id=%s AND title='سابقه continuity'
        """,
        [seed_data["link_id"]],
    ) == target_before
    assert _count(
        """
        SELECT COUNT(*) FROM clinical.record_import_ledger
        WHERE tenant_id=1 AND source_id='source-continuity-truncated'
        """,
        [],
    ) == ledger_before


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_same_source_id_cannot_be_reused_for_a_different_sqlite_database(
    seed_data,
    tmp_path,
):
    source_id = "source-continuity-database-identity"
    first = _source(
        tmp_path / "source-a.db",
        source_patient_id=1,
        accounting_patient_id=seed_data["patient_id"],
        history_id=10,
    )
    SpecialistRecordImporter(
        sqlite_path=first,
        source_id=source_id,
        tenant_id=1,
        apply=True,
    ).run()

    second = _source(
        tmp_path / "source-b.db",
        source_patient_id=2,
        accounting_patient_id=seed_data["patient_id"],
        history_id=None,
    )
    with pytest.raises(ImportConflictError, match="Do not reuse a source-id"):
        SpecialistRecordImporter(
            sqlite_path=second,
            source_id=source_id,
            tenant_id=1,
            apply=True,
        ).run()

    # The attempted mapping for source patient row 2 was inside the outer
    # transaction and must not survive the continuity failure.
    assert _count(
        """
        SELECT COUNT(*) FROM clinical.record_import_ledger
        WHERE tenant_id=1 AND source_id=%s
          AND source_table='patient_links' AND source_row_id=2
        """,
        [source_id],
    ) == 0
    assert _count(
        """
        SELECT COUNT(*) FROM clinical.record_import_ledger
        WHERE tenant_id=1 AND source_id=%s
        """,
        [source_id],
    ) == 2
