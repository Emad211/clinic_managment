"""Generates and manages follow-up worklist tasks."""
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.common.utils import today_str

REASON_LABELS = {
    'refill': 'تجدید دارو',
    'uncontrolled': 'کنترل‌نشده',
    'lapsed': 'بدون مراجعه اخیر',
    'visit_due': 'موعد ویزیت',
    'monitoring': 'پایش (ADA)',
    'screening': 'غربالگری (ADA)',
    'vaccine': 'واکسیناسیون (ADA)',
    'manual': 'دستی',
}


class FollowupService:
    def __init__(self, repo: FollowupRepository | None = None):
        self.repo = repo or FollowupRepository()

    def generate(self) -> dict:
        """Scan patients and open follow-up tasks (idempotent — no duplicates while open)."""
        db = get_db()
        created = {'refill': 0, 'uncontrolled': 0, 'lapsed': 0, 'ada': 0}

        # 1) Refill due (medication refill_due_date within 7 days)
        rows = db.execute(
            """SELECT DISTINCT p.id, m.drug_name, m.refill_due_date
               FROM patient_links p JOIN patient_medications m ON m.patient_link_id=p.id AND m.is_active=1
               WHERE p.is_active=1 AND m.refill_due_date IS NOT NULL
                 AND m.refill_due_date <= date('now','+3 hours','+30 minutes','+7 days')"""
        ).fetchall()
        for r in rows:
            if not self.repo.exists_open(r['id'], 'refill'):
                self.repo.create(r['id'], reason='refill',
                                 detail=f"داروی {r['drug_name']} تا {r['refill_due_date']}",
                                 due_date=r['refill_due_date'])
                created['refill'] += 1

        # 2) Uncontrolled (latest hba1c or systolic at/above the editable danger threshold)
        from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository
        rules = ClinicalRulesRepository()
        hba1c_danger = (rules.get('hba1c') or {}).get('danger') or 8
        sys_danger = (rules.get('bp_systolic') or {}).get('danger') or 140
        rows = db.execute(
            """SELECT p.id FROM patient_links p WHERE p.is_active=1 AND (
                 (SELECT v.value FROM vital_readings v WHERE v.patient_link_id=p.id AND v.type='hba1c'
                    ORDER BY v.measured_at DESC LIMIT 1) >= ?
                 OR (SELECT v.value FROM vital_readings v WHERE v.patient_link_id=p.id AND v.type='bp_systolic'
                    ORDER BY v.measured_at DESC LIMIT 1) >= ?
               )""",
            (hba1c_danger, sys_danger),
        ).fetchall()
        for r in rows:
            if not self.repo.exists_open(r['id'], 'uncontrolled'):
                self.repo.create(r['id'], reason='uncontrolled',
                                 detail='آخرین شاخص‌ها خارج از محدوده کنترل', due_date=today_str())
                created['uncontrolled'] += 1

        # 3) Lapsed (no vital reading in last 120 days)
        rows = db.execute(
            """SELECT p.id FROM patient_links p WHERE p.is_active=1 AND NOT EXISTS (
                 SELECT 1 FROM vital_readings v WHERE v.patient_link_id=p.id
                   AND v.measured_at >= datetime('now','+3 hours','+30 minutes','-120 days'))"""
        ).fetchall()
        for r in rows:
            if not self.repo.exists_open(r['id'], 'lapsed'):
                self.repo.create(r['id'], reason='lapsed',
                                 detail='بیش از ۴ ماه بدون ثبت شاخص', due_date=today_str())
                created['lapsed'] += 1

        # 4) Rule-driven monitoring / screening / vaccination (ADA engine)
        try:
            from src.services.followup_engine import generate_all
            created['ada'] = generate_all()
        except Exception:
            pass

        return created
