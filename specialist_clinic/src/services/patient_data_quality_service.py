"""Patient-level data quality exceptions for point-of-use frontend display.

The service reports source-backed structural problems only. It does not interpret a
clinical value or create a parallel recommendation engine.
"""
from __future__ import annotations

from collections import Counter
import sqlite3

from src.adapters.sqlite.core import get_db
from src.services.clinical_reconciliation_service import (
    ClinicalReconciliationService,
)


_SEVERITY_ORDER = {"danger": 0, "warn": 1, "info": 2}


class PatientDataQualityService:
    def __init__(self, db: sqlite3.Connection | None = None):
        self.db = db or get_db()

    @staticmethod
    def _digits(value: object) -> str:
        return "".join(char for char in str(value or "") if char.isdigit())

    @staticmethod
    def _issue(
        code: str,
        *,
        severity: str,
        title: str,
        detail: str,
        tab: str,
        action_label: str,
        action_kind: str = "tab",
        anchor: str | None = None,
        count: int = 1,
    ) -> dict:
        return {
            "code": code,
            "severity": severity,
            "title": title,
            "detail": detail,
            "tab": tab,
            "action_label": action_label,
            "action_kind": action_kind,
            "anchor": anchor,
            "count": int(count),
        }

    def _identity_issues(self, patient: dict) -> list[dict]:
        issues = []
        phone = self._digits(patient.get("phone_number"))
        if not phone:
            issues.append(
                self._issue(
                    "IDENTITY_PHONE_MISSING",
                    severity="danger",
                    title="شماره موبایل ثبت نشده است",
                    detail="تماس، پیام و بازیابی بیمار بدون شماره معتبر ممکن نیست.",
                    tab="summary",
                    anchor="workspace-identity-editor",
                    action_label="تکمیل هویت",
                )
            )
        elif len(phone) < 10:
            issues.append(
                self._issue(
                    "IDENTITY_PHONE_INVALID",
                    severity="danger",
                    title="شماره موبایل معتبر نیست",
                    detail=f"شماره فعلی فقط {len(phone)} رقم قابل‌استفاده دارد.",
                    tab="summary",
                    anchor="workspace-identity-editor",
                    action_label="اصلاح شماره",
                )
            )
        else:
            duplicates = int(
                self.db.execute(
                    """SELECT COUNT(*) AS count FROM patient_links
                       WHERE is_active=1 AND id<>?
                         AND REPLACE(REPLACE(REPLACE(REPLACE(
                           COALESCE(phone_number,''),' ',''),'-',''),'(',''),')','')=?""",
                    (int(patient["id"]), phone),
                ).fetchone()["count"]
                or 0
            )
            if duplicates:
                issues.append(
                    self._issue(
                        "IDENTITY_PHONE_DUPLICATE",
                        severity="danger",
                        title="شماره موبایل در پرونده دیگری تکرار شده است",
                        detail=f"{duplicates} پرونده فعال دیگر همین شماره را دارند.",
                        tab="summary",
                        anchor="workspace-identity-editor",
                        action_label="بررسی هویت",
                        count=duplicates,
                    )
                )
        if not str(patient.get("national_id") or "").strip():
            issues.append(
                self._issue(
                    "IDENTITY_NATIONAL_ID_MISSING",
                    severity="warn",
                    title="کد ملی ثبت نشده است",
                    detail="تشخیص پرونده تکراری و اتصال دقیق به منابع دیگر ضعیف می‌شود.",
                    tab="summary",
                    anchor="workspace-identity-editor",
                    action_label="ثبت کد ملی",
                )
            )
        if not str(patient.get("birthdate") or "").strip():
            issues.append(
                self._issue(
                    "IDENTITY_BIRTHDATE_MISSING",
                    severity="info",
                    title="تاریخ تولد ثبت نشده است",
                    detail="گروه‌بندی سنی و بعضی برنامه‌های مراقبت دقیق نخواهند بود.",
                    tab="summary",
                    anchor="workspace-identity-editor",
                    action_label="تکمیل مشخصات",
                )
            )
        return issues

    def _medication_issues(self, patient_link_id: int) -> list[dict]:
        rows = self.db.execute(
            """SELECT medication.*,catalog.generic_fa,catalog.drug_class_key,
                      catalog.is_active AS catalog_active
               FROM patient_medications medication
               LEFT JOIN drug_catalog catalog
                 ON catalog.id=medication.drug_catalog_id
               WHERE medication.patient_link_id=? AND medication.is_active=1""",
            (int(patient_link_id),),
        ).fetchall()
        legacy = 0
        missing_dose = 0
        missing_schedule = 0
        inactive_catalog = 0
        identity_mismatch = 0
        for row in rows:
            item = dict(row)
            if not item.get("drug_catalog_id"):
                legacy += 1
            elif not int(item.get("catalog_active") or 0):
                inactive_catalog += 1
            elif (
                str(item.get("generic_fa") or "").strip()
                != str(item.get("drug_name") or "").strip()
                or str(item.get("drug_class_key") or "").strip()
                != str(item.get("drug_class") or "").strip()
            ):
                identity_mismatch += 1
            if not str(item.get("dose") or "").strip():
                missing_dose += 1
            if not str(item.get("schedule") or "").strip():
                missing_schedule += 1
        issues = []
        if legacy:
            issues.append(
                self._issue(
                    "MEDICATION_CATALOG_MISSING",
                    severity="danger",
                    title="داروی فعال بدون هویت کاتالوگی",
                    detail=f"{legacy} داروی فعال هنوز Free-text است و باید تطبیق شود.",
                    tab="meds",
                    anchor="workspace-medications-title",
                    action_label="بررسی داروها",
                    count=legacy,
                )
            )
        if inactive_catalog or identity_mismatch:
            total = inactive_catalog + identity_mismatch
            issues.append(
                self._issue(
                    "MEDICATION_CATALOG_CONFLICT",
                    severity="danger",
                    title="هویت دارو با کاتالوگ سازگار نیست",
                    detail=f"{total} دارو به کاتالوگ غیرفعال یا نام/کلاس ناسازگار متصل است.",
                    tab="meds",
                    anchor="workspace-medications-title",
                    action_label="اصلاح تطبیق",
                    count=total,
                )
            )
        if missing_dose:
            issues.append(
                self._issue(
                    "MEDICATION_DOSE_MISSING",
                    severity="warn",
                    title="دوز داروی فعال ناقص است",
                    detail=f"برای {missing_dose} داروی فعال دوز ثبت نشده است.",
                    tab="meds",
                    anchor="workspace-medications-title",
                    action_label="تکمیل دوز",
                    count=missing_dose,
                )
            )
        if missing_schedule:
            issues.append(
                self._issue(
                    "MEDICATION_SCHEDULE_MISSING",
                    severity="warn",
                    title="برنامه مصرف دارو ناقص است",
                    detail=f"برای {missing_schedule} داروی فعال برنامه مصرف ثبت نشده است.",
                    tab="meds",
                    anchor="workspace-medications-title",
                    action_label="تکمیل برنامه",
                    count=missing_schedule,
                )
            )
        return issues

    def _lab_issues(self, patient_link_id: int) -> list[dict]:
        rows = self.db.execute(
            """SELECT result.*,catalog.name_fa,catalog.unit AS catalog_unit,
                      catalog.ref_low AS catalog_ref_low,
                      catalog.ref_high AS catalog_ref_high,
                      catalog.is_active AS catalog_active
               FROM lab_results result
               LEFT JOIN lab_test_catalog catalog
                 ON catalog.test_key=result.test_key
               WHERE result.patient_link_id=?""",
            (int(patient_link_id),),
        ).fetchall()
        free_text = 0
        invalid_key = 0
        unit_mismatch = 0
        range_mismatch = 0
        for row in rows:
            item = dict(row)
            if not str(item.get("test_key") or "").strip():
                free_text += 1
                continue
            if not item.get("name_fa") or not int(item.get("catalog_active") or 0):
                invalid_key += 1
                continue
            if str(item.get("unit") or "").strip() != str(
                item.get("catalog_unit") or ""
            ).strip():
                unit_mismatch += 1
            for result_key, catalog_key in (
                ("ref_low", "catalog_ref_low"),
                ("ref_high", "catalog_ref_high"),
            ):
                result_value = item.get(result_key)
                catalog_value = item.get(catalog_key)
                if result_value is None and catalog_value is None:
                    continue
                if result_value is None or catalog_value is None:
                    range_mismatch += 1
                    break
                if float(result_value) != float(catalog_value):
                    range_mismatch += 1
                    break
        issues = []
        if free_text:
            issues.append(
                self._issue(
                    "LAB_CATALOG_MISSING",
                    severity="danger",
                    title="آزمایش بدون کد استاندارد",
                    detail=f"{free_text} نتیجه آزمایش هنوز Free-text است.",
                    tab="clinical",
                    anchor="workspace-labs-title",
                    action_label="بررسی آزمایش‌ها",
                    count=free_text,
                )
            )
        if invalid_key:
            issues.append(
                self._issue(
                    "LAB_CATALOG_INVALID",
                    severity="danger",
                    title="کد آزمایش معتبر نیست",
                    detail=f"{invalid_key} نتیجه به آزمایش حذف‌شده یا ناموجود متصل است.",
                    tab="clinical",
                    anchor="workspace-labs-title",
                    action_label="اصلاح کد آزمایش",
                    count=invalid_key,
                )
            )
        if unit_mismatch:
            issues.append(
                self._issue(
                    "LAB_UNIT_MISMATCH",
                    severity="warn",
                    title="واحد آزمایش با کاتالوگ متفاوت است",
                    detail=f"واحد {unit_mismatch} نتیجه با واحد استاندارد سازگار نیست.",
                    tab="clinical",
                    anchor="workspace-labs-title",
                    action_label="بررسی واحد",
                    count=unit_mismatch,
                )
            )
        if range_mismatch:
            issues.append(
                self._issue(
                    "LAB_REFERENCE_MISMATCH",
                    severity="warn",
                    title="محدوده مرجع آزمایش متفاوت است",
                    detail=f"محدوده مرجع {range_mismatch} نتیجه با کاتالوگ جاری فرق دارد.",
                    tab="clinical",
                    anchor="workspace-labs-title",
                    action_label="بررسی محدوده",
                    count=range_mismatch,
                )
            )
        return issues

    def _reconciliation_issues(self, patient_link_id: int) -> list[dict]:
        status = ClinicalReconciliationService().patient_status(
            int(patient_link_id)
        )
        issues = []
        for collection in status.values():
            if collection.get("clinical_complete"):
                continue
            tone = str(collection.get("tone") or "warn")
            severity = "danger" if tone == "danger" else "warn"
            issues.append(
                self._issue(
                    f"RECONCILIATION_{collection['collection_key'].upper()}",
                    severity=severity,
                    title=(
                        f"{collection['label']}: {collection['state_fa']}"
                    ),
                    detail=str(collection.get("detail") or "نیازمند مرور است."),
                    tab="clinical",
                    action_kind="reconciliation",
                    action_label="مرور اختلاف",
                    count=max(int(collection.get("unresolved_conflict_count") or 0), 1),
                )
            )
        return issues

    def _appointment_issues(self, patient_link_id: int) -> list[dict]:
        stale = int(
            self.db.execute(
                """SELECT COUNT(*) AS count FROM appointments
                   WHERE patient_link_id=? AND status='scheduled'
                     AND datetime(scheduled_at)<
                         datetime('now','+3 hours','+30 minutes')""",
                (int(patient_link_id),),
            ).fetchone()["count"]
            or 0
        )
        if not stale:
            return []
        return [
            self._issue(
                "APPOINTMENT_STALE_SCHEDULED",
                severity="danger",
                title="نوبت گذشته هنوز تعیین‌تکلیف نشده است",
                detail=f"{stale} نوبت گذشته همچنان در وضعیت برنامه‌ریزی‌شده است.",
                tab="encounters",
                action_label="تعیین وضعیت نوبت",
                count=stale,
            )
        ]

    def _acquisition_issues(self, patient_link_id: int) -> list[dict]:
        row = self.db.execute(
            """SELECT source_code,referrer_patient_link_id,referrer_name
               FROM growth_leads
               WHERE patient_link_id=? AND status='CONVERTED'
               ORDER BY converted_at DESC,id DESC LIMIT 1""",
            (int(patient_link_id),),
        ).fetchone()
        if not row:
            return [
                self._issue(
                    "ACQUISITION_SOURCE_UNKNOWN",
                    severity="info",
                    title="منبع جذب دقیق ثبت نشده است",
                    detail="این بیمار پیش از Lead Pipeline ثبت شده و کانال جذب قابل‌اندازه‌گیری نیست.",
                    tab="summary",
                    action_kind="acquisition",
                    action_label="ثبت منبع جذب",
                )
            ]
        if (
            row["source_code"] == "PATIENT_REFERRAL"
            and not row["referrer_patient_link_id"]
        ):
            return [
                self._issue(
                    "ACQUISITION_REFERRER_UNRESOLVED",
                    severity="warn",
                    title="بیمار معرف با پرونده واقعی متصل نیست",
                    detail=str(row["referrer_name"] or "نام معرف ثبت نشده است."),
                    tab="summary",
                    action_kind="acquisition",
                    action_label="تطبیق معرف",
                )
            ]
        return []

    def build(self, patient_link_id: int) -> dict:
        patient = self.db.execute(
            "SELECT * FROM patient_links WHERE id=?",
            (int(patient_link_id),),
        ).fetchone()
        if not patient:
            return {
                "issues": [],
                "counts": {"danger": 0, "warn": 0, "info": 0, "total": 0},
                "by_tab": {},
            }
        patient_dict = dict(patient)
        issues = [
            *self._identity_issues(patient_dict),
            *self._medication_issues(int(patient_link_id)),
            *self._lab_issues(int(patient_link_id)),
            *self._reconciliation_issues(int(patient_link_id)),
            *self._appointment_issues(int(patient_link_id)),
            *self._acquisition_issues(int(patient_link_id)),
        ]
        issues.sort(
            key=lambda item: (
                _SEVERITY_ORDER.get(item["severity"], 9),
                item["tab"],
                item["title"],
            )
        )
        counts = Counter(item["severity"] for item in issues)
        by_tab: dict[str, list[dict]] = {}
        for issue in issues:
            by_tab.setdefault(issue["tab"], []).append(issue)
        return {
            "issues": issues,
            "counts": {
                "danger": int(counts.get("danger", 0)),
                "warn": int(counts.get("warn", 0)),
                "info": int(counts.get("info", 0)),
                "total": len(issues),
            },
            "by_tab": by_tab,
        }


__all__ = ["PatientDataQualityService"]
