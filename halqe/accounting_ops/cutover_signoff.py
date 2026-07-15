from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
import re
import stat
from typing import Any, Iterable, Mapping

from accounting_ops.cutover_signoff_models import AccountingCutoverSignoffReport
from platform_core.backup_canonical import BackupVerificationError, file_sha256


class AccountingCutoverSignoffError(BackupVerificationError):
    pass


_REQUIRED_SCOPES = {"all", "morning", "evening", "night"}
_REQUIRED_HUMAN_CHECKS = {"cash", "insurance", "payroll", "invoice_samples"}
_SENSITIVE_KEYS = {
    "nationalid", "nationalcode", "national_id", "phone", "phonenumber",
    "mobile", "mobilenumber", "patientname", "fullname", "address", "birthdate",
    "کدملی", "شمارهملی", "شمارهتلفن", "شمارههمراه", "شماره موبایل", "نامبیمار",
}
_MOBILE = re.compile(r"(?<!\d)(?:\+?98|0098|0)?9(?:[\s()\-]*\d){9}(?!\d)")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _key(value: Any) -> str:
    return re.sub(r"[^0-9a-zA-Zآ-ی]+", "", str(value)).lower()


_SENSITIVE_NORMALIZED = {_key(value) for value in _SENSITIVE_KEYS}


def _integer(value: Any, *, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AccountingCutoverSignoffError(f"{label} must be an integer") from exc


def _private_json(path: str | Path, *, label: str) -> tuple[dict[str, Any], str]:
    source = Path(path).expanduser().absolute()
    if source.is_symlink() or not source.is_file():
        raise AccountingCutoverSignoffError(f"{label} must be a regular non-symlink file")
    if stat.S_IMODE(source.stat().st_mode) & 0o077:
        raise AccountingCutoverSignoffError(f"{label} must be owner-only (chmod 600)")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AccountingCutoverSignoffError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise AccountingCutoverSignoffError(f"{label} must contain one JSON object")
    return payload, file_sha256(source)


def _timestamp(value: Any, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise AccountingCutoverSignoffError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise AccountingCutoverSignoffError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def _contains_sensitive(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            _key(key) in _SENSITIVE_NORMALIZED or _contains_sensitive(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive(item) for item in value)
    if isinstance(value, str):
        return bool(_MOBILE.search(value.translate(_DIGITS)))
    return False


def _consecutive(values: list[date]) -> bool:
    return all(
        right - left == timedelta(days=1)
        for left, right in zip(values, values[1:])
    )


def _dual_key(payload: Mapping[str, Any]) -> str:
    if payload.get("date_from") != payload.get("date_to"):
        raise AccountingCutoverSignoffError("Each cutover dual-run report must cover one day")
    try:
        day = date.fromisoformat(str(payload["date_from"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise AccountingCutoverSignoffError(
            "Dual-run report date must use YYYY-MM-DD"
        ) from exc
    shift = payload.get("shift") or "all"
    if shift not in _REQUIRED_SCOPES:
        raise AccountingCutoverSignoffError(f"Unsupported dual-run scope: {shift}")
    return f"{day.isoformat()}:{shift}"


def _expected_hashes(packet: Mapping[str, Any]) -> Mapping[str, Any]:
    hashes = packet.get("artifact_sha256")
    if not isinstance(hashes, Mapping):
        raise AccountingCutoverSignoffError("Sign-off packet artifact_sha256 is required")
    return hashes


def verify_accounting_cutover_signoff(
    *,
    packet_path: str | Path,
    import_verification_path: str | Path,
    restore_verification_path: str | Path,
    dual_run_report_paths: Iterable[str | Path],
    source_id: str,
    tenant_id: int,
) -> AccountingCutoverSignoffReport:
    packet, packet_sha = _private_json(packet_path, label="signoff_packet")
    import_report, import_sha = _private_json(
        import_verification_path, label="import_verification"
    )
    restore_report, restore_sha = _private_json(
        restore_verification_path, label="restore_verification"
    )
    dual_reports: dict[str, tuple[dict[str, Any], str]] = {}
    for path in dual_run_report_paths:
        payload, digest = _private_json(path, label="dual_run_report")
        key = _dual_key(payload)
        if key in dual_reports:
            raise AccountingCutoverSignoffError(f"Duplicate dual-run report scope: {key}")
        dual_reports[key] = (payload, digest)
    if not dual_reports:
        raise AccountingCutoverSignoffError("At least one dual-run report is required")

    required_days = _integer(
        packet.get("required_consecutive_days"),
        label="required_consecutive_days",
    )
    if required_days < 1 or required_days > 31:
        raise AccountingCutoverSignoffError(
            "required_consecutive_days must be between 1 and 31"
        )
    command_tenant = _integer(tenant_id, label="tenant_id")

    report = AccountingCutoverSignoffReport(
        decision="GO",
        source_id=source_id,
        tenant_id=command_tenant,
        reviewed_by=str(packet.get("reviewed_by") or "") or None,
        reviewed_at=str(packet.get("reviewed_at") or "") or None,
        required_consecutive_days=required_days,
        observed_dates=sorted({key.split(":", 1)[0] for key in dual_reports}),
        artifact_sha256={
            "signoff_packet": packet_sha,
            "import_verification": import_sha,
            "restore_verification": restore_sha,
            "dual_run_reports": {
                key: digest for key, (_payload, digest) in sorted(dual_reports.items())
            },
        },
    )
    now = datetime.now(UTC) + timedelta(minutes=5)
    try:
        reviewed_at = _timestamp(packet.get("reviewed_at"), label="reviewed_at")
    except AccountingCutoverSignoffError:
        reviewed_at = None
    try:
        packet_tenant = _integer(packet.get("tenant_id"), label="packet tenant_id")
    except AccountingCutoverSignoffError:
        packet_tenant = -1
    report.add(
        "packet_identity",
        packet.get("version") == 1
        and packet.get("source_id") == source_id
        and packet_tenant == command_tenant,
        "Packet version, source-id and tenant must match the command",
    )
    report.add(
        "packet_approval",
        packet.get("decision") == "approved"
        and bool(report.reviewed_by)
        and reviewed_at is not None
        and reviewed_at <= now,
        "Final accounting reviewer and timezone-aware approval are required",
    )
    report.add(
        "packet_phi_free",
        not _contains_sensitive(packet),
        "The sign-off packet must not contain direct patient identifiers or phone numbers",
    )

    hashes = _expected_hashes(packet)
    expected_dual = hashes.get("dual_run_reports")
    actual_dual = report.artifact_sha256["dual_run_reports"]
    report.add(
        "artifact_hash_binding",
        hashes.get("import_verification") == import_sha
        and hashes.get("restore_verification") == restore_sha
        and isinstance(expected_dual, Mapping)
        and dict(expected_dual) == actual_dual,
        "Packet hashes must exactly bind every supplied machine-verification artifact",
    )

    try:
        import_tenant = _integer(
            import_report.get("tenant_id"), label="import verification tenant_id"
        )
    except AccountingCutoverSignoffError:
        import_tenant = -1
    import_ok = (
        import_report.get("decision") == "VERIFIED"
        and import_report.get("source_id") == source_id
        and import_tenant == command_tenant
        and not import_report.get("errors")
        and all(item.get("status") == "PASS" for item in import_report.get("checks", []))
    )
    report.add(
        "import_verification",
        import_ok,
        "Historical accounting import verification must be completely VERIFIED",
    )
    restore_ok = (
        restore_report.get("decision") == "VERIFIED"
        and not restore_report.get("errors")
        and all(item.get("status") == "PASS" for item in restore_report.get("checks", []))
    )
    report.add(
        "backup_restore_verification",
        restore_ok,
        "Backup restore evidence must be completely VERIFIED",
    )

    dual_ok = True
    scopes_by_day: dict[str, set[str]] = {}
    source_hashes_by_day: dict[str, set[tuple[str, str]]] = {}
    for key, (payload, _digest) in dual_reports.items():
        day, scope = key.split(":", 1)
        scopes_by_day.setdefault(day, set()).add(scope)
        source_hashes_by_day.setdefault(day, set()).add(
            (
                str(payload.get("source_file_sha256") or ""),
                str(payload.get("source_manifest_sha256") or ""),
            )
        )
        try:
            dual_tenant = _integer(payload.get("tenant_id"), label="dual tenant_id")
        except AccountingCutoverSignoffError:
            dual_tenant = -1
        dual_ok = dual_ok and (
            payload.get("decision") == "GO"
            and not payload.get("differences")
            and not payload.get("errors")
            and payload.get("source_id") == source_id
            and dual_tenant == command_tenant
            and payload.get("financial_source") == payload.get("financial_target")
            and payload.get("payroll_source") == payload.get("payroll_target")
        )
    dates = sorted(date.fromisoformat(day) for day in scopes_by_day)
    complete_scopes = all(
        scopes == _REQUIRED_SCOPES for scopes in scopes_by_day.values()
    )
    daily_source_identity = all(
        len(values) == 1 and all(next(iter(values)))
        for values in source_hashes_by_day.values()
    )
    report.add(
        "dual_run_reports",
        dual_ok,
        "Every daily and shift dual-run report must be exact GO with no differences",
        report_count=len(dual_reports),
    )
    report.add(
        "dual_run_scope_coverage",
        len(dates) >= required_days
        and complete_scopes
        and _consecutive(dates)
        and daily_source_identity,
        "Required consecutive dates must each include all/morning/evening/night from one daily snapshot",
        observed_dates=[item.isoformat() for item in dates],
        scopes={key: sorted(value) for key, value in sorted(scopes_by_day.items())},
    )

    human = packet.get("human_checks")
    human_ok = isinstance(human, Mapping) and set(human) >= _REQUIRED_HUMAN_CHECKS
    if human_ok:
        for key in _REQUIRED_HUMAN_CHECKS:
            item = human[key]
            try:
                item_time = _timestamp(item.get("reviewed_at"), label=f"{key}.reviewed_at")
            except (AccountingCutoverSignoffError, AttributeError):
                human_ok = False
                break
            human_ok = human_ok and (
                isinstance(item, Mapping)
                and item.get("status") == "approved"
                and bool(str(item.get("reviewer") or "").strip())
                and item_time <= now
            )
            if key == "invoice_samples":
                try:
                    human_ok = human_ok and int(item.get("sample_count") or 0) > 0
                except (TypeError, ValueError):
                    human_ok = False
    report.add(
        "human_financial_review",
        human_ok,
        "Cash, insurance, payroll and invoice sample reviews must all be approved",
    )

    discrepancies = packet.get("discrepancies", [])
    discrepancies_ok = isinstance(discrepancies, list)
    if discrepancies_ok:
        for item in discrepancies:
            discrepancies_ok = discrepancies_ok and (
                isinstance(item, Mapping)
                and item.get("status") == "fixed"
                and bool(str(item.get("owner") or "").strip())
                and bool(str(item.get("resolution") or "").strip())
            )
    report.add(
        "discrepancies_closed",
        discrepancies_ok,
        "Every recorded discrepancy must be fixed with owner and resolution; deferred risk is not accepted",
        discrepancy_count=len(discrepancies) if isinstance(discrepancies, list) else None,
    )
    report.decision = "GO" if not report.errors else "NO_GO"
    return report
