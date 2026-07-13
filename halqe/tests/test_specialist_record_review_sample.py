"""Clinician review-sample tests bound to a successful import verifier."""
from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
import stat
import uuid

from django.core.management import call_command
from django.core.management.base import CommandError
import pytest

from clinical.secure_report_io import write_private_text
from clinical.specialist_record_import import SpecialistRecordImporter
from clinical.specialist_record_review_sample import (
    ReviewCandidate,
    SpecialistRecordReviewSampler,
)
from tests.test_specialist_record_import import _build_source


def _augment_all_scenarios(source: Path, suffix: str) -> None:
    db = sqlite3.connect(source)
    second_condition = f"etl_second_condition_{suffix}"
    date_flag = f"etl_date_flag_{suffix}"
    db.execute(
        """
        INSERT INTO conditions
            (id, name, code, is_active, is_chronic, display_order)
        VALUES (9701, 'بیماری دوم نمونه', ?, 1, 1, 971)
        """,
        [second_condition],
    )
    db.execute(
        """
        INSERT INTO patient_conditions
            (id, patient_link_id, condition_id, stage, onset_date,
             notes, is_active, diagnosed_at)
        VALUES (9702, 1001, 9701, 'stage-2', '2023-01-01',
                'تشخیص دوم', 1, '2025-01-08 08:00:00')
        """
    )
    db.execute(
        """
        INSERT INTO medication_events
            (id, patient_link_id, medication_id, drug_name, event_type,
             dose, event_date, note, created_by, created_at)
        VALUES (9703, 1001, 9303, ?, 'dose_change', '10 mg',
                '2025-01-15', 'افزایش دوز', 'testuser',
                '2025-01-15 10:00:00')
        """,
        [f"داروی بیمار {suffix}"],
    )
    db.execute(
        "UPDATE allergies SET severity='severe' WHERE id=9401"
    )
    db.execute(
        """
        INSERT INTO flag_catalog
            (id, flag_key, label, flag_type, options, category,
             display_order, is_active, notes, record_section)
        VALUES (9704, ?, 'تاریخ معاینه نمونه', 'date', NULL,
                'exam', 972, 1, NULL, 'exam')
        """,
        [date_flag],
    )
    db.execute(
        """
        INSERT INTO patient_flags
            (id, patient_link_id, flag_key, value, recorded_by, updated_at)
        VALUES (9705, 1001, ?, '2025-01-20', 'testuser',
                '2025-01-20 09:00:00')
        """,
        [date_flag],
    )
    db.commit()
    db.close()


def _verified_rehearsal(seed_data, tmp_path):
    suffix = uuid.uuid4().hex
    source_id = f"review-sample-{suffix}"
    source = _build_source(
        tmp_path / "review-source.db",
        accounting_patient_id=seed_data["patient_id"],
        national_id="1234567890",
        suffix=suffix,
    )
    _augment_all_scenarios(source, suffix)

    apply = SpecialistRecordImporter(
        sqlite_path=source,
        source_id=source_id,
        tenant_id=1,
        apply=True,
    ).run()
    replay = SpecialistRecordImporter(
        sqlite_path=source,
        source_id=source_id,
        tenant_id=1,
        apply=True,
    ).run()
    apply_report = write_private_text(
        tmp_path / "review-apply.json",
        json.dumps(apply.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
    )
    replay_report = write_private_text(
        tmp_path / "review-replay.json",
        json.dumps(replay.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
    )
    verification_report = tmp_path / "review-verification.json"
    call_command(
        "verify_specialist_record_import",
        sqlite=str(source),
        apply_report=str(apply_report),
        replay_report=str(replay_report),
        source_id=source_id,
        tenant_id=1,
        report=str(verification_report),
        stdout=StringIO(),
        verbosity=0,
    )
    return source_id, source, verification_report


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_review_packet_is_deterministic_private_and_covers_present_scenarios(
    seed_data,
    tmp_path,
):
    source_id, _source, verification = _verified_rehearsal(seed_data, tmp_path)
    output_one = tmp_path / "clinical-review-one.json"
    output_two = tmp_path / "clinical-review-two.json"

    stdout = StringIO()
    call_command(
        "generate_specialist_record_review_sample",
        verification_report=str(verification),
        source_id=source_id,
        tenant_id=1,
        per_scenario=1,
        max_patients=25,
        report=str(output_one),
        stdout=stdout,
        verbosity=0,
    )
    call_command(
        "generate_specialist_record_review_sample",
        verification_report=str(verification),
        source_id=source_id,
        tenant_id=1,
        per_scenario=1,
        max_patients=25,
        report=str(output_two),
        stdout=StringIO(),
        verbosity=0,
    )

    first = json.loads(output_one.read_text(encoding="utf-8"))
    second = json.loads(output_two.read_text(encoding="utf-8"))
    assert stat.S_IMODE(output_one.stat().st_mode) == 0o600
    assert first["patients"] == second["patients"]
    assert first["coverage"] == second["coverage"]
    assert len(first["patients"]) == 1
    assert first["patients"][0]["source_patient_link_id"] == 1001
    assert first["patients"][0]["cockpit_path"].startswith("/patients/")

    present = [
        row for row in first["coverage"].values()
        if row["eligible_patients"] > 0
    ]
    assert len(present) == len(first["scenarios"])
    assert all(row["status"] == "covered" for row in present)
    assert not first["warnings"]
    assert first["signoff_template"]["decision"] is None

    rendered = output_one.read_text(encoding="utf-8")
    for direct_identifier in (
        "علی رضایی",
        "1234567890",
        "09120000001",
    ):
        assert direct_identifier not in rendered
        assert direct_identifier not in stdout.getvalue()
    assert "Specialist clinical review sample generated" in stdout.getvalue()


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_review_packet_requires_matching_go_verification_report(seed_data, tmp_path):
    no_go = write_private_text(
        tmp_path / "no-go.json",
        json.dumps(
            {
                "decision": "NO_GO",
                "source_id": "review-no-go",
                "tenant_id": 1,
                "source_file_sha256": "a" * 64,
                "source_manifest_sha256": "b" * 64,
            }
        ) + "\n",
    )
    with pytest.raises(CommandError, match="decision=GO"):
        call_command(
            "generate_specialist_record_review_sample",
            verification_report=str(no_go),
            source_id="review-no-go",
            tenant_id=1,
            report=str(tmp_path / "should-not-exist.json"),
            verbosity=0,
        )
    assert not (tmp_path / "should-not-exist.json").exists()


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_review_packet_is_bound_to_source_and_tenant(seed_data, tmp_path):
    source_id, _source, verification = _verified_rehearsal(seed_data, tmp_path)
    with pytest.raises(CommandError, match="source_id"):
        call_command(
            "generate_specialist_record_review_sample",
            verification_report=str(verification),
            source_id=source_id + "-wrong",
            tenant_id=1,
            report=str(tmp_path / "wrong-source.json"),
            verbosity=0,
        )
    with pytest.raises(CommandError, match="tenant_id"):
        call_command(
            "generate_specialist_record_review_sample",
            verification_report=str(verification),
            source_id=source_id,
            tenant_id=2,
            report=str(tmp_path / "wrong-tenant.json"),
            verbosity=0,
        )


def test_greedy_selection_maximizes_coverage_and_is_stable(tmp_path):
    sampler = SpecialistRecordReviewSampler(
        verification_report_path=tmp_path / "unused.json",
        source_id="unit-selection",
        tenant_id=1,
        per_scenario=1,
        max_patients=2,
    )
    candidates = [
        ReviewCandidate(
            source_patient_link_id=1,
            target_patient_link_id=101,
            patient_uuid="00000000-0000-0000-0000-000000000001",
            scenarios=["multiple_conditions", "laboratory_result"],
            feature_counts={},
        ),
        ReviewCandidate(
            source_patient_link_id=2,
            target_patient_link_id=102,
            patient_uuid="00000000-0000-0000-0000-000000000002",
            scenarios=[
                "multiple_conditions",
                "medication_lifecycle",
                "laboratory_result",
            ],
            feature_counts={},
        ),
        ReviewCandidate(
            source_patient_link_id=3,
            target_patient_link_id=103,
            patient_uuid="00000000-0000-0000-0000-000000000003",
            scenarios=["severe_allergy"],
            feature_counts={},
        ),
    ]

    selected, coverage, warnings = sampler._select(candidates)
    assert [item.source_patient_link_id for item in selected] == [2, 3]
    assert coverage["multiple_conditions"]["status"] == "covered"
    assert coverage["medication_lifecycle"]["status"] == "covered"
    assert coverage["laboratory_result"]["status"] == "covered"
    assert coverage["severe_allergy"]["status"] == "covered"
    assert not warnings
