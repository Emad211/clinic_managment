"""Generates and manages follow-up worklist tasks."""
from src.adapters.sqlite.followups_repo import FollowupRepository

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
    def __init__(self, repo: FollowupRepository | None = None):
        self.repo = repo or FollowupRepository()

    def generate(self) -> dict:
        """Run the canonical engagement engine for worklist routes only."""
        from src.services.engagement_service import EngagementService
        result = EngagementService().run_all(worklist_only=True)
        return {'worklist': result['worklist']}
