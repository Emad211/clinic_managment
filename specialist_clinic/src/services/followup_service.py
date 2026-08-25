"""Generates and manages follow-up worklist tasks and internal clinical alerts."""
import logging

from src.adapters.sqlite.followups_repo import FollowupRepository
from src.services.clinical_alert_service import ClinicalAlertService
from src.services.followup_engine import ClinicalV2FollowupService

logger = logging.getLogger(__name__)


def _run_clinical(label: str, fn, *args) -> dict:
    """Run one separable clinical generator in isolation.

    The analytical/clinical layer is architecturally separable: if it is off or
    raises, the always-on administrative engagement engine must still run. A
    failure is surfaced LOUDLY (logged with stack + funnelled into ``issues`` so
    the route flashes it) and the clinical suggestion is suppressed fail-closed —
    it is never converted into a silent success. It just cannot 500 the caller.
    """
    try:
        result = fn(*args) or {}
    except Exception as exc:  # clinical layer must never break the admin flow
        logger.exception("clinical generator failed label=%s", label)
        return {"created": 0, "issues": [f"{label} به علت خطا اجرا نشد: {exc}"]}
    return {
        "created": int(result.get("created") or 0),
        "issues": list(result.get("issues") or []),
    }


REASON_LABELS = {
    "encounter_plan": "تعهد طرح ویزیت",
    'refill': 'تجدید دارو',
    'uncontrolled': 'پیگیری قدیمی',
    'lapsed': 'بدون مراجعه اخیر',
    'visit_due': 'موعد ویزیت',
    'recall': 'دعوتِ بازگشت',
    'monitoring': 'پایش',
    'screening': 'غربالگری',
    'vaccine': 'واکسیناسیون',
    'manual': 'دستی',
}


class FollowupService:
    def __init__(
        self,
        repo: FollowupRepository | None = None,
        clinical_v2=None,
        clinical_alerts=None,
    ):
        self.repo = repo or FollowupRepository()
        self.clinical_v2 = clinical_v2 or ClinicalV2FollowupService(repo=self.repo)
        self.clinical_alerts = clinical_alerts or ClinicalAlertService()

    def generate(self) -> dict:
        """Generate governed clinical alerts/tasks, then distinct admin events."""
        from src.services.engagement_service import EngagementService

        alerts = _run_clinical("هشدار بالینی", self.clinical_alerts.generate_all)
        clinical = _run_clinical("پیگیری بالینی", self.clinical_v2.generate_all)
        engagement = EngagementService().run_all(worklist_only=True)
        return {
            "worklist": engagement["worklist"] + clinical["created"],
            "clinical_v2": clinical["created"],
            "clinical_alerts": alerts["created"],
            "issues": [*alerts["issues"], *clinical["issues"]],
        }

    def generate_patient(self, patient_link_id: int) -> dict:
        """Generate one patient's alerts, v2 tasks and separate admin tasks."""
        from src.services.engagement_service import EngagementService

        alerts = _run_clinical(
            "هشدار بالینی", self.clinical_alerts.generate_patient, patient_link_id
        )
        clinical = _run_clinical(
            "پیگیری بالینی", self.clinical_v2.generate_patient, patient_link_id
        )
        engagement = EngagementService().dispatch_patient(
            patient_link_id, worklist_only=True
        )
        return {
            "worklist": engagement["worklist"] + clinical["created"],
            "clinical_v2": clinical["created"],
            "clinical_alerts": alerts["created"],
            "issues": [*alerts["issues"], *clinical["issues"]],
        }
