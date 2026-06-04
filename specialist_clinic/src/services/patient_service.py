"""Patient enrollment + chronic profile logic."""
from typing import Optional
from src.adapters.sqlite.patients_repo import PatientRepository
from src.adapters import accounting_bridge


class PatientService:
    def __init__(self, repo: PatientRepository | None = None):
        self.repo = repo or PatientRepository()

    def search_accounting(self, query: str) -> list[dict]:
        """Search the accounting DB (read-only) and flag which are already enrolled."""
        results = accounting_bridge.search_patients(query)
        for r in results:
            nid = r.get('national_id')
            r['already_enrolled'] = bool(nid and self.repo.get_by_national_id(nid))
        return results

    def enroll_from_accounting(self, accounting_patient_id: int, enrolled_by: str) -> Optional[int]:
        """Pull a patient from the accounting DB and create a local chronic-care link."""
        p = accounting_bridge.get_patient_by_id(accounting_patient_id)
        if not p:
            return None
        nid = p.get('national_id')
        if nid:
            existing = self.repo.get_by_national_id(nid)
            if existing:
                return existing['id']
        return self.repo.create(
            national_id=nid,
            accounting_patient_id=p.get('id'),
            full_name=p.get('full_name') or '—',
            phone_number=p.get('phone_number'),
            gender=p.get('gender'),
            birthdate=p.get('birthdate'),
            address=p.get('address'),
            enrolled_by=enrolled_by,
        )

    def enroll_manual(self, *, full_name, national_id, phone_number, gender,
                      birthdate, address, enrolled_by) -> Optional[int]:
        """Create a local patient not (yet) in the accounting DB."""
        if national_id:
            existing = self.repo.get_by_national_id(national_id)
            if existing:
                return existing['id']
            # Link to accounting if a matching national_id exists there.
            acc = accounting_bridge.get_patient_by_national_id(national_id)
            acc_id = acc.get('id') if acc else None
        else:
            acc_id = None
        return self.repo.create(
            national_id=national_id or None,
            accounting_patient_id=acc_id,
            full_name=full_name,
            phone_number=phone_number,
            gender=gender,
            birthdate=birthdate,
            address=address,
            enrolled_by=enrolled_by,
        )

    def get_full_profile(self, pid: int) -> Optional[dict]:
        patient = self.repo.get_by_id(pid)
        if not patient:
            return None
        # Real-time accounting visit history (if linked).
        visit_history = []
        if patient.get('accounting_patient_id'):
            visit_history = accounting_bridge.get_visit_history(patient['accounting_patient_id'])
        return {
            'patient': patient,
            'conditions': self.repo.get_patient_conditions(pid),
            'medications': self.repo.get_medications(pid, active_only=False),
            'allergies': self.repo.get_allergies(pid),
            'visit_history': visit_history,
        }
