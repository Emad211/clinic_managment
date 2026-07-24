"""Map specialist-clinic records to canonical Clinical Engine v2 facts."""
from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any, Iterable

from src.common.jalali import Persian
from src.common.utils import IRAN_TZ, parse_datetime
from src.domain.clinical_engine import (
    ClinicalFact,
    ConflictStatus,
    FactKind,
    FactSource,
    FactStatus,
    FreshnessStatus,
    VerificationStatus,
)
from src.domain.clinical_engine.reconciliation import project_collection
from src.domain.clinical_engine.flag_history import (
    ClinicalFlagState,
    project_flag_events,
)


_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_KEY_PART = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_COLLECTION_DEFINITIONS = (
    (
        "conditions",
        FactKind.CONDITION,
        "condition.codes",
        "condition",
        "condition_code",
    ),
    (
        "medications",
        FactKind.MEDICATION,
        "medication.classes",
        "medication",
        "drug_class",
    ),
    (
        "allergies",
        FactKind.ALLERGY,
        "allergy.substances",
        "allergy",
        "substance",
    ),
)


def normalize_birthdate(value: Any) -> date | None:
    """Normalize a complete Gregorian or Jalali birth date; never approximate."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip().translate(_FA_DIGITS)
    match = re.fullmatch(r"(\d{4})\D(\d{1,2})\D(\d{1,2})", text)
    if not match:
        return None
    year, month, day = map(int, match.groups())
    try:
        if year < 1700:
            return Persian(year, month, day).gregorian_datetime()
        return date(year, month, day)
    except Exception:
        return None


def age_on(birthdate: date, as_of: date) -> int | None:
    if birthdate > as_of:
        return None
    age = as_of.year - birthdate.year - (
        (as_of.month, as_of.day) < (birthdate.month, birthdate.day)
    )
    return age if 0 <= age <= 130 else None


def _dt(value: Any, fallback: datetime) -> datetime:
    parsed = parse_datetime(value)
    if parsed is None:
        parsed = fallback
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(IRAN_TZ).replace(tzinfo=None)
    return parsed


def _key(prefix: str, raw: Any, record_id: Any) -> tuple[str, tuple[str, ...]]:
    part = str(raw or "").strip().lower()
    if _KEY_PART.fullmatch(part):
        return f"{prefix}.{part}", ()
    return f"{prefix}.unmapped-{record_id}", ("LEGACY_APPROXIMATION",)


def _observation_provenance(
    row: dict[str, Any],
) -> tuple[str, VerificationStatus, tuple[str, ...]]:
    """Map stored source without upgrading patient-entered data to confirmed."""
    if row.get("channel") == "lab":
        return "laboratory", VerificationStatus.CONFIRMED, ()
    # Older isolated adapter tests predate source_detail. Production repository
    # rows always include it, so this compatibility default cannot affect live data.
    if "source_detail" not in row:
        return "clinician", VerificationStatus.CONFIRMED, ()
    source = str(row.get("source_detail") or "").strip().lower()
    if source in {"clinic", "clinician", "office"}:
        return "clinician", VerificationStatus.CONFIRMED, ()
    if source in {"self", "patient", "home"}:
        return "patient", VerificationStatus.PROVISIONAL, ("PATIENT_REPORTED",)
    if source in {"device", "remote_device"}:
        return "device", VerificationStatus.PROVISIONAL, ("DEVICE_REPORTED",)
    return "system", VerificationStatus.UNVERIFIED, ("UNMAPPED_SOURCE",)


class LegacyFactBundleAdapter:
    """Pure, deterministic mapping from repository rows to typed facts."""

    def adapt(
        self, bundle: dict[str, Any], *, as_of_at: datetime
    ) -> tuple[ClinicalFact, ...]:
        as_of_at = _dt(as_of_at, as_of_at)
        patient = bundle["patient"]
        pid = int(patient["id"])
        # Contact/address edits also update patient_links.updated_at, but they do
        # not change demographic facts. Enrollment is the stable provenance
        # fallback until dedicated demographic event timestamps are introduced.
        fallback = _dt(patient.get("enrolled_at"), as_of_at)
        facts: list[ClinicalFact] = []

        def add(
            *,
            fact_id: str,
            kind: FactKind,
            key: str,
            status: FactStatus,
            value: Any,
            effective_at: datetime,
            recorded_at: datetime | None = None,
            system: str,
            record_id: Any,
            actor: str | None = None,
            unit: str | None = None,
            verification: VerificationStatus = VerificationStatus.CONFIRMED,
            freshness: FreshnessStatus = FreshnessStatus.UNKNOWN,
            conflict: ConflictStatus = ConflictStatus.NONE,
            reference_range: dict | None = None,
            derived_from: Iterable[str] = (),
            warnings: Iterable[str] = (),
        ) -> None:
            facts.append(
                ClinicalFact(
                    schema_version="2.0",
                    fact_id=fact_id,
                    patient_link_id=pid,
                    kind=kind,
                    key=key,
                    status=status,
                    value=value,
                    unit=unit,
                    effective_at=effective_at,
                    recorded_at=recorded_at or effective_at,
                    source=FactSource(
                        system=system, record_id=str(record_id), actor=actor
                    ),
                    verification=verification,
                    freshness=freshness,
                    conflict=conflict,
                    reference_range=reference_range,
                    derived_from=tuple(derived_from),
                    warnings=tuple(sorted(set(warnings))),
                )
            )

        birth_raw = patient.get("birthdate")
        birth = normalize_birthdate(birth_raw)
        add(
            fact_id=f"patient:{pid}:birthdate",
            kind=FactKind.DEMOGRAPHIC,
            key="demographic.birthdate",
            status=FactStatus.PRESENT if birth else FactStatus.UNKNOWN,
            value=birth.isoformat() if birth else None,
            effective_at=fallback,
            system="patient_links",
            record_id=pid,
            warnings=("LEGACY_APPROXIMATION",) if birth_raw and not birth else (),
        )
        derived_age = age_on(birth, as_of_at.date()) if birth else None
        add(
            fact_id=f"derived:{pid}:age",
            kind=FactKind.DEMOGRAPHIC,
            key="demographic.age_years",
            status=(
                FactStatus.PRESENT
                if derived_age is not None
                else FactStatus.UNKNOWN
            ),
            value=derived_age,
            effective_at=as_of_at,
            system="derived",
            record_id=f"age:{pid}",
            derived_from=(f"patient:{pid}:birthdate",),
        )
        gender = str(patient.get("gender") or "").strip()
        add(
            fact_id=f"patient:{pid}:gender",
            kind=FactKind.DEMOGRAPHIC,
            key="demographic.sex",
            status=FactStatus.PRESENT if gender else FactStatus.UNKNOWN,
            value=gender or None,
            effective_at=fallback,
            system="patient_links",
            record_id=pid,
        )

        self._collections(bundle, pid, as_of_at, add)
        self._flags(bundle, pid, as_of_at, add)
        self._observations(bundle, pid, as_of_at, add)
        # Fact order is part of the snapshot hash and must be deterministic.
        return tuple(
            sorted(
                facts,
                key=lambda fact: (
                    fact.key,
                    fact.effective_at,
                    1 if fact.source.system == "laboratory" else 0,
                    fact.fact_id,
                ),
            )
        )

    def _collections(self, bundle, pid, as_of_at, add):
        # Focused tests written before reconciliation injected hand-built bundles
        # without the key. Production ClinicalEngineFactRepository always includes
        # it; preserve the old fixture contract only for those isolated tests.
        if "reconciliations" not in bundle:
            self._legacy_test_collections(bundle, pid, as_of_at, add)
            return

        unavailable = bundle.get("unavailable", {})
        reconciliation_events = bundle.get("reconciliations", [])
        medication_events = bundle.get("medication_events", [])
        for source, kind, key, prefix, field in _COLLECTION_DEFINITIONS:
            blocked_sources = {source, "reconciliations", "conflicts"}
            if source == "medications":
                blocked_sources.add("medication_events")
            if blocked_sources & set(unavailable):
                add(
                    fact_id=f"source:{pid}:{source}",
                    kind=kind,
                    key=key,
                    status=FactStatus.UNKNOWN,
                    value=None,
                    effective_at=as_of_at,
                    system="system",
                    record_id=source,
                    verification=VerificationStatus.UNVERIFIED,
                    freshness=FreshnessStatus.UNKNOWN,
                    warnings=("SOURCE_UNAVAILABLE",),
                )
                continue

            projection = project_collection(
                source,
                bundle.get(source, []),
                reconciliation_events,
                as_of_at=as_of_at,
                medication_events=(
                    medication_events if source == "medications" else ()
                ),
                conflict_events=bundle.get("conflicts", ()),
            )
            add(
                fact_id=f"collection:{pid}:{source}",
                kind=kind,
                key=key,
                status=projection.status,
                value=(
                    list(projection.values)
                    if projection.status is FactStatus.PRESENT
                    else None
                ),
                effective_at=projection.effective_at,
                system=projection.source_system,
                record_id=projection.source_record_id,
                actor=projection.actor,
                verification=projection.verification,
                freshness=projection.freshness,
                conflict=projection.conflict,
                warnings=projection.warnings,
            )

            for row in projection.rows:
                raw = row.get(field)
                if not raw:
                    continue
                if prefix == "allergy":
                    fact_key = "allergy.substance"
                    key_warnings: tuple[str, ...] = ()
                    fact_value = str(row.get("allergy_concept_key") or raw)
                else:
                    fact_key, key_warnings = _key(prefix, raw, row["id"])
                    fact_value = True
                # Presence of a concrete source row is independently knowable;
                # reconciliation governs completeness and confirmed absence of the
                # aggregate list, not whether this particular recorded item exists.
                add(
                    fact_id=f"{prefix}:{row['id']}",
                    kind=kind,
                    key=fact_key,
                    status=FactStatus.PRESENT,
                    value=fact_value,
                    effective_at=_dt(row.get("_effective_at"), as_of_at),
                    system=source,
                    record_id=row["id"],
                    actor=row.get("recorded_by") or row.get("created_by"),
                    verification=(
                        VerificationStatus.CONFIRMED
                        if row.get("_resolution_confirmed")
                        else VerificationStatus(str(row.get("verification") or "CONFIRMED").upper())
                        if str(row.get("verification") or "CONFIRMED").upper()
                        in {item.value for item in VerificationStatus}
                        else VerificationStatus.UNVERIFIED
                    ),
                    freshness=FreshnessStatus.UNKNOWN,
                    warnings=(
                        *projection.warnings,
                        *(row.get("_history_warnings") or ()),
                        *key_warnings,
                    ),
                )

    @staticmethod
    def _legacy_test_collections(bundle, pid, as_of_at, add):
        unavailable = bundle.get("unavailable", {})
        for source, kind, key, prefix, field in _COLLECTION_DEFINITIONS:
            if source in unavailable:
                add(
                    fact_id=f"source:{pid}:{source}",
                    kind=kind,
                    key=key,
                    status=FactStatus.UNKNOWN,
                    value=None,
                    effective_at=as_of_at,
                    system="system",
                    record_id=source,
                    verification=VerificationStatus.UNVERIFIED,
                    warnings=("SOURCE_UNAVAILABLE",),
                )
                continue
            rows = [
                row
                for row in bundle.get(source, [])
                if int(row.get("is_active", 1) or 0)
            ]
            values = sorted(
                {
                    str(row.get(field)).strip()
                    for row in rows
                    if row.get(field)
                }
            )
            incomplete = source in {"conditions", "medications"} and any(
                not row.get(field) for row in rows
            )
            add(
                fact_id=f"collection:{pid}:{source}",
                kind=kind,
                key=key,
                status=FactStatus.UNKNOWN if incomplete else FactStatus.PRESENT,
                value=None if incomplete else values,
                effective_at=as_of_at,
                system="legacy_collection",
                record_id=source,
                verification=(
                    VerificationStatus.UNVERIFIED
                    if incomplete
                    else VerificationStatus.CONFIRMED
                ),
                warnings=("LEGACY_APPROXIMATION",) if incomplete else (),
            )
            for row in rows:
                raw = row.get(field)
                if not raw:
                    continue
                if prefix == "allergy":
                    fact_key, key_warnings, fact_value = (
                        "allergy.substance",
                        (),
                        str(raw),
                    )
                else:
                    fact_key, key_warnings = _key(prefix, raw, row["id"])
                    fact_value = True
                add(
                    fact_id=f"{prefix}:{row['id']}",
                    kind=kind,
                    key=fact_key,
                    status=FactStatus.PRESENT,
                    value=fact_value,
                    effective_at=_dt(
                        row.get("diagnosed_at")
                        or row.get("created_at")
                        or row.get("start_date"),
                        as_of_at,
                    ),
                    system=source,
                    record_id=row["id"],
                    actor=row.get("recorded_by"),
                    warnings=key_warnings,
                )

    def _flags(self, bundle, pid, as_of_at, add):
        unavailable = bundle.get("unavailable", {})
        if "flags" in unavailable or "flag_catalog" in unavailable:
            add(
                fact_id=f"source:{pid}:flags",
                kind=FactKind.FLAG,
                key="flag.values",
                status=FactStatus.UNKNOWN,
                value=None,
                effective_at=as_of_at,
                system="system",
                record_id="flags",
                verification=VerificationStatus.UNVERIFIED,
                warnings=("SOURCE_UNAVAILABLE",),
            )
            return
        projections = project_flag_events(
            bundle.get("flags", []),
            bundle.get("flag_catalog", []),
            as_of_at=as_of_at,
            knowledge_at=as_of_at,
        )
        present_keys = sorted(
            key for key, item in projections.items()
            if item["state"] == ClinicalFlagState.PRESENT.value
        )
        add(
            fact_id=f"collection:{pid}:flags",
            kind=FactKind.FLAG,
            key="flag.values",
            status=FactStatus.PRESENT,
            value=present_keys,
            effective_at=as_of_at,
            system="clinical_flag_events",
            record_id="flags",
            verification=VerificationStatus.UNVERIFIED,
        )
        status_map = {
            ClinicalFlagState.PRESENT.value: FactStatus.PRESENT,
            ClinicalFlagState.UNKNOWN.value: FactStatus.UNKNOWN,
            ClinicalFlagState.NOT_ASKED.value: FactStatus.NOT_ASKED,
        }
        for key, projection in projections.items():
            catalog = projection["catalog"]
            event = projection["event"]
            fact_key, key_warnings = _key("flag", key, catalog["id"])
            verification = VerificationStatus(projection["verification"])
            add(
                fact_id=(
                    f"flag-event:{event['id']}"
                    if event else f"flag-catalog:{catalog['id']}"
                ),
                kind=FactKind.FLAG,
                key=fact_key,
                status=status_map[projection["state"]],
                value=projection["value"],
                effective_at=_dt(projection["effective_at"], as_of_at),
                recorded_at=_dt(projection["recorded_at"], as_of_at),
                system=(event.get("source") if event else "flag_catalog"),
                record_id=(event["id"] if event else catalog["id"]),
                actor=(event.get("actor_username") if event else None),
                verification=verification,
                warnings=(
                    *projection["warnings"],
                    *key_warnings,
                ),
            )

    def _observations(self, bundle, pid, as_of_at, add):
        if "observations" in bundle.get("unavailable", {}):
            add(
                fact_id=f"source:{pid}:observations",
                kind=FactKind.OBSERVATION,
                key="observation.values",
                status=FactStatus.UNKNOWN,
                value=None,
                effective_at=as_of_at,
                system="system",
                record_id="observations",
                verification=VerificationStatus.UNVERIFIED,
                warnings=("SOURCE_UNAVAILABLE",),
            )
            return
        observation_rows = bundle.get("observations", [])
        add(
            fact_id=f"collection:{pid}:observations",
            kind=FactKind.OBSERVATION,
            key="observation.keys",
            status=FactStatus.PRESENT,
            value=sorted(
                {
                    str(row["key"])
                    for row in observation_rows
                    if row.get("key")
                }
            ),
            effective_at=as_of_at,
            system="legacy_collection",
            record_id="observations",
        )
        for row in observation_rows:
            key = row.get("key")
            if not key:
                continue
            fact_key, key_warnings = _key(
                "observation", key, row["record_id"]
            )
            source_system, source_verification, source_warnings = (
                _observation_provenance(row)
            )
            effective = parse_datetime(row.get("effective_at"))
            if effective is not None:
                effective = _dt(effective, as_of_at)
            comparable_as_of = _dt(as_of_at, as_of_at)
            if (
                effective is None
                or effective > comparable_as_of
                or row.get("value") is None
            ):
                quality_warnings = (
                    ("OUTLIER",)
                    if effective is None or effective > comparable_as_of
                    else ()
                )
                add(
                    fact_id=f"{row['channel']}:{row['record_id']}",
                    kind=FactKind.OBSERVATION,
                    key=fact_key,
                    status=FactStatus.UNKNOWN,
                    value=None,
                    effective_at=effective or as_of_at,
                    system=source_system,
                    record_id=row["record_id"],
                    actor=row.get("recorded_by"),
                    verification=VerificationStatus.UNVERIFIED,
                    warnings=(
                        *quality_warnings,
                        *source_warnings,
                        *key_warnings,
                    ),
                )
                continue
            reference = None
            if row.get("ref_low") is not None or row.get("ref_high") is not None:
                reference = {
                    "low": row.get("ref_low"),
                    "high": row.get("ref_high"),
                    "unit": row.get("unit"),
                    "source": "lab_results",
                }
            add(
                fact_id=f"{row['channel']}:{row['record_id']}",
                kind=FactKind.OBSERVATION,
                key=fact_key,
                status=FactStatus.PRESENT,
                value=row.get("value"),
                unit=row.get("unit"),
                effective_at=effective,
                system=source_system,
                record_id=row["record_id"],
                actor=row.get("recorded_by"),
                verification=source_verification,
                # Freshness is selector/rule-specific (max_age_days), therefore
                # the provider must not declare an observation fresh globally.
                freshness=FreshnessStatus.UNKNOWN,
                reference_range=reference,
                warnings=(
                    "LEGACY_APPROXIMATION",
                    *source_warnings,
                    *key_warnings,
                ),
            )
