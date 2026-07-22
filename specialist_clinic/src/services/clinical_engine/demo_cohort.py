"""Idempotent creation of the synthetic ten-patient activation cohort."""

from src.adapters.sqlite.flags_repo import ClinicalFlagsRepository
from src.adapters.sqlite.patients_repo import PatientRepository
from src.adapters.sqlite.vitals_repo import VitalsRepository
from src.services.activity_logger import log_activity


class DemoCohortService:
    def ensure(self, *, actor: str) -> int:
        # Reuse the single canonical cohort definition used by the developer
        # seed command; this import does not create a second Flask app.
        from seed_demo_data import PATIENTS, trend

        patients = PatientRepository()
        vitals = VitalsRepository()
        flags = ClinicalFlagsRepository()
        created = 0
        for spec in PATIENTS:
            if patients.get_by_national_id(spec["nid"]):
                continue
            patient_id = patients.create(
                national_id=spec["nid"], accounting_patient_id=None,
                full_name=spec["name"], phone_number=spec["phone"],
                gender=spec["gender"], birthdate=spec["birth"], address=None,
                enrolled_by="clinical-v2-safety-test",
            )
            for condition_id in spec["conditions"]:
                patients.add_condition(patient_id, condition_id)
            for key, value in spec.get("flags", {}).items():
                flags.set_flag(patient_id, key, value)
            for vital_type, (start, end, dates) in spec["vitals"].items():
                for date, value in zip(dates, trend(start, end, len(dates))):
                    vitals.add_reading(
                        patient_id, vtype=vital_type, value=round(value, 1),
                        measured_at=date + " 10:00:00",
                        recorded_by="clinical-v2-safety-test",
                    )
            for name, drug_class, dose, start, change, stop in spec.get("meds", []):
                medication_id = patients.add_medication(
                    patient_id, drug_name=name, dose=dose, schedule=None,
                    start_date=start, refill_due_date="2026-07-01", notes=None,
                    drug_class=drug_class, created_by="clinical-v2-safety-test",
                )
                if change:
                    patients.change_dose(
                        medication_id, change[1], change_date=change[0],
                        created_by="clinical-v2-safety-test",
                    )
                if stop:
                    patients.stop_medication(
                        medication_id, end_date=stop,
                        created_by="clinical-v2-safety-test",
                    )
            created += 1
        if created:
            log_activity(
                "clinical_v2_demo_cohort_prepare",
                f"Created {created} synthetic activation patients",
                user_id=0, username=(actor or "manager").strip(),
            )
        return created
