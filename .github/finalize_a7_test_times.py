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
    '''    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.common.utils import iran_now
    from src.services.patient_service import PatientService

    patient_id = int(PatientService().enroll_from_accounting(1, "pytest-a7"))
    # The effective timestamp is captured after enrollment, so it is never before the
    # specialist cutover. Repository recorded_at is generated afterwards, so the same
    # timestamp also cannot be in the future. Equal effective times preserve event order
    # through the append-only event IDs without relying on wall-clock sleeps.
    start = iran_now()
    active = start
    completed = start
    repo = CareJourneyRepository()
''',
    1,
)
text = text.replace('effective_at="2026-07-26 11:00:00",', 'effective_at=start,', 1)
text = text.replace('effective_at="2026-07-26 11:05:00",', 'effective_at=active,', 2)
text = text.replace('effective_at="2026-07-26 11:30:00",', 'effective_at=completed,', 1)
path.write_text(text, encoding="utf-8")
Path(__file__).unlink()
