"""Generates and manages follow-up worklist tasks."""
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.services.followup_engine import ClinicalV2FollowupService

REASON_LABELS = {
    'refill': 'تجدید دارو',
    'uncontrolled': 'کنترل‌نشده',
    'lapsed': 'بدون مراجعه اخیر',
    'visit_due': 'موعد ویزیت',
    'recall': 'دعوتِ بازگشت',
    'monitoring': 'پایش',
    'screening': 'غربالگری',
    'vaccine': 'واکسیناسیون',
    'manual': 'دستی',
}


class FollowupService:
    def __init__(self, repo: FollowupRepository | None = None, clinical_v2=None):
        self.repo = repo or FollowupRepository()
        self.clinical_v2 = clinical_v2 or ClinicalV2FollowupService(repo=self.repo)

    def generate(self) -> dict:
        """Generate v2 clinical tasks, then legacy/admin worklist events."""
        from src.services.engagement_service import EngagementService
        clinical = self.clinical_v2.generate_all()
        engagement = EngagementService().run_all(worklist_only=True)
        return {
            "worklist": engagement["worklist"] + clinical["created"],
            "clinical_v2": clinical["created"],
            "issues": clinical["issues"],
        }

    def generate_patient(self, patient_link_id: int) -> dict:
        """Generate one patient's v2 clinical and distinct admin/legacy tasks."""
        from src.services.engagement_service import EngagementService
        clinical = self.clinical_v2.generate_patient(patient_link_id)
        engagement = EngagementService().dispatch_patient(
            patient_link_id, worklist_only=True
        )
        return {
            "worklist": engagement["worklist"] + clinical["created"],
            "clinical_v2": clinical["created"],
            "issues": clinical["issues"],
        }
