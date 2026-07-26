from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "specialist_clinic/tests/test_specialist_payer_adjustments_a7.py"
text = path.read_text(encoding="utf-8")
text = text.replace(
    '''    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.services.patient_service import PatientService

    patient_id = int(PatientService().enroll_from_accounting(1, "pytest-a7"))
    repo = CareJourneyRepository()
''',
    '''    from datetime import timedelta
    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.common.utils import iran_now
    from src.services.patient_service import PatientService

    patient_id = int(PatientService().enroll_from_accounting(1, "pytest-a7"))
    start = iran_now() + timedelta(seconds=1)
    active = start + timedelta(minutes=1)
    completed = active + timedelta(minutes=20)
    repo = CareJourneyRepository()
''',
    1,
)
text = text.replace('effective_at="2026-07-26 11:00:00",', 'effective_at=start,', 1)
text = text.replace('effective_at="2026-07-26 11:05:00",', 'effective_at=active,', 2)
text = text.replace('effective_at="2026-07-26 11:30:00",', 'effective_at=completed,', 1)
path.write_text(text, encoding="utf-8")
Path(__file__).unlink()
