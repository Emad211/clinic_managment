"""Generates and manages follow-up worklist tasks and internal clinical alerts."""
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.services.clinical_alert_service import ClinicalAlertService
from src.services.followup_engine import ClinicalV2FollowupService

REASON_LABELS = {
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

        alerts = self.clinical_alerts.generate_all()
        clinical = self.clinical_v2.generate_all()
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

        alerts = self.clinical_alerts.generate_patient(patient_link_id)
        clinical = self.clinical_v2.generate_patient(patient_link_id)
        engagement = EngagementService().dispatch_patient(
            patient_link_id, worklist_only=True
        )
        return {
            "worklist": engagement["worklist"] + clinical["created"],
            "clinical_v2": clinical["created"],
            "clinical_alerts": alerts["created"],
            "issues": [*alerts["issues"], *clinical["issues"]],
        }
