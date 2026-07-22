"""Map current specialist-clinic records to canonical Clinical Engine v2 facts."""

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


_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}
_KEY_PART = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


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


def _typed_flag(value: Any, flag_type: str | None) -> Any:
    text = str(value)
    if flag_type in {"boolean", "bool"}:
        lowered = text.strip().lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
    return text


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
    # Older tests/adapters predate source_detail. Their vital rows represented
    # clinic measurements, so preserve that narrow compatibility default. The
    # production repository always supplies source_detail explicitly.
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
        # not change demographic facts. Using updated_at here made an unrelated
        # contact edit change the clinical snapshot hash without advancing the
        # clinical revision. Enrollment is the stable provenance fallback until
        # dedicated demographic event timestamps are introduced.
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
                    recorded_at=effective_at,
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
        birth_status = FactStatus.PRESENT if birth else FactStatus.UNKNOWN
        add(
            fact_id=f"patient:{pid}:birthdate",
            kind=FactKind.DEMOGRAPHIC,
            key="demographic.birthdate",
            status=birth_status,
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
        # The order is part of the snapshot contract. At the same effective time
        # a lab row follows a clinic row, keeping deterministic ordering without
        # dropping either source (conflict detection needs both).
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
        definitions = (
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
        unavailable = bundle.get("unavailable", {})
        for source, kind, key, prefix, field in definitions:
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
            rows = bundle.get(source, [])
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
                status=(FactStatus.UNKNOWN if incomplete else FactStatus.PRESENT),
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
                effective = _dt(
                    row.get("diagnosed_at")
                    or row.get("created_at")
                    or row.get("start_date"),
                    as_of_at,
                )
                if prefix == "allergy":
                    fact_key = "allergy.substance"
                    key_warnings = ()
                    fact_value = str(raw)
                else:
                    fact_key, key_warnings = _key(prefix, raw, row["id"])
                    fact_value = True
                add(
                    fact_id=f"{prefix}:{row['id']}",
                    kind=kind,
                    key=fact_key,
                    status=FactStatus.PRESENT,
                    value=fact_value,
                    effective_at=effective,
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
        values = {row["flag_key"]: row for row in bundle.get("flags", [])}
        add(
            fact_id=f"collection:{pid}:flags",
            kind=FactKind.FLAG,
            key="flag.values",
            status=FactStatus.PRESENT,
            value=sorted(values),
            effective_at=as_of_at,
            system="legacy_collection",
            record_id="flags",
        )
        for catalog in bundle.get("flag_catalog", []):
            key = catalog["flag_key"]
            row = values.get(key)
            fact_key, key_warnings = _key("flag", key, catalog["id"])
            add(
                fact_id=f"flag:{pid}:{key}",
                kind=FactKind.FLAG,
                key=fact_key,
                status=FactStatus.PRESENT if row else FactStatus.NOT_ASKED,
                value=(
                    _typed_flag(row["value"], catalog.get("flag_type"))
                    if row
                    else None
                ),
                effective_at=(
                    _dt(row.get("updated_at"), as_of_at) if row else as_of_at
                ),
                system="patient_flags" if row else "flag_catalog",
                record_id=row["id"] if row else catalog["id"],
                actor=row.get("recorded_by") if row else None,
                verification=(
                    VerificationStatus.CONFIRMED
                    if row
                    else VerificationStatus.UNVERIFIED
                ),
                warnings=key_warnings,
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
            channel = row["channel"]
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
                    fact_id=f"{channel}:{row['record_id']}",
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
                fact_id=f"{channel}:{row['record_id']}",
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
