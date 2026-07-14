"""Visibility tests for source rows reused against different canonical metadata."""
from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from clinical.specialist_record_import import SpecialistRecordImporter


def _source(path: Path, *, accounting_patient_id: int) -> Path:
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE patient_links (
            id INTEGER PRIMARY KEY,
            accounting_patient_id INTEGER,
            national_id TEXT,
            full_name TEXT,
            sms_opt_out INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE conditions (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            code TEXT,
            is_active INTEGER DEFAULT 1,
            is_chronic INTEGER DEFAULT 1,
            display_order INTEGER DEFAULT 100,
            description TEXT,
            icon TEXT,
            color TEXT
        );
        """
    )
    db.execute(
        """
        INSERT INTO patient_links
            (id, accounting_patient_id, full_name, sms_opt_out, is_active)
        VALUES (1, ?, 'نام مبدأ در گزارش کپی نمی‌شود', 0, 1)
        """,
        [accounting_patient_id],
    )
    db.execute(
        """
        INSERT INTO conditions
            (id, name, code, is_active, is_chronic, display_order,
             description, icon, color)
        VALUES (77, 'نام متفاوت مبدأ', 'diabetes', 1, 1, 777,
                'شرح متفاوت و محرمانه', 'source-icon', 'source-color')
        """
    )
    db.commit()
    db.close()
    return path


@pytest.mark.django_db(databases=["default", "accounting_read"])
@pytest.mark.parametrize("apply", [False, True])
def test_reused_canonical_metadata_difference_is_reported_without_values(
    seed_data,
    tmp_path,
    apply,
):
    source = _source(
        tmp_path / ("reuse-apply.db" if apply else "reuse-dry.db"),
        accounting_patient_id=seed_data["patient_id"],
    )
    report = SpecialistRecordImporter(
        sqlite_path=source,
        source_id=f"canonical-reuse-warning-{'apply' if apply else 'dry'}",
        tenant_id=1,
        apply=apply,
    ).run()

    warnings = "\n".join(report.warnings)
    assert "conditions#77" in warnings
    assert "Canonical target differs" in warnings
    assert "نام متفاوت مبدأ" not in warnings
    assert "شرح متفاوت و محرمانه" not in warnings


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_patient_link_asymmetric_merge_does_not_emit_generic_divergence_warning(
    seed_data,
    tmp_path,
):
    source = tmp_path / "patient-link-reuse.db"
    db = sqlite3.connect(source)
    db.execute(
        """
        CREATE TABLE patient_links (
            id INTEGER PRIMARY KEY,
            accounting_patient_id INTEGER,
            national_id TEXT,
            full_name TEXT,
            sms_opt_out INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        )
        """
    )
    db.execute(
        """
        INSERT INTO patient_links
            (id, accounting_patient_id, national_id, full_name,
             sms_opt_out, is_active)
        VALUES (88, ?, 'do-not-report', 'نام متفاوت مبدأ', 0, 1)
        """,
        [seed_data["patient_id"]],
    )
    db.commit()
    db.close()

    report = SpecialistRecordImporter(
        sqlite_path=source,
        source_id="patient-link-merge-warning-exclusion",
        tenant_id=1,
        apply=False,
    ).run()
    assert not any(
        "Canonical target differs" in warning and "patient_links#88" in warning
        for warning in report.warnings
    )


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_timezone_equivalent_insert_does_not_emit_false_divergence_warning(
    seed_data,
    tmp_path,
):
    source = tmp_path / "timezone-equivalent.db"
    db = sqlite3.connect(source)
    db.executescript(
        """
        CREATE TABLE patient_links (
            id INTEGER PRIMARY KEY,
            accounting_patient_id INTEGER,
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
            (id, accounting_patient_id, sms_opt_out, is_active)
        VALUES (1, ?, 0, 1)
        """,
        [seed_data["patient_id"]],
    )
    db.execute(
        """
        INSERT INTO medical_history
            (id, patient_link_id, title, note, since, created_at)
        VALUES (91, 1, 'سابقه timezone تست', 'شرح', '2020-01-01',
                '2025-01-01 10:00:00')
        """
    )
    db.commit()
    db.close()

    report = SpecialistRecordImporter(
        sqlite_path=source,
        source_id="timezone-equivalent-target-digest",
        tenant_id=1,
        apply=True,
    ).run()
    assert not any(
        "Canonical target differs" in warning and "medical_history#91" in warning
        for warning in report.warnings
    )
