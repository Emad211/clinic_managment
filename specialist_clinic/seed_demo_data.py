# -*- coding: utf-8 -*-
"""Development seed: 10 varied T2D patients with ~2 years of data.

Idempotent — patients are keyed by synthetic national_ids TEST0001..TEST0010,
so re-running does NOT duplicate. Use this dataset for all testing during
development. Run:  .venv\\Scripts\\python.exe seed_demo_data.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from src.app import create_app


def month_dates(y, m, count, step):
    out = []
    for _ in range(count):
        out.append(f"{y:04d}-{m:02d}-01")
        m += step
        while m > 12:
            m -= 12
            y += 1
    return out


def trend(a, b, n):
    return [a + (b - a) * i / (n - 1) for i in range(n)]


D12 = month_dates(2024, 6, 12, 2)   # every 2 months, 24 months
D6 = month_dates(2024, 6, 6, 4)     # quarterly-ish (A1c), 24 months
D3 = ["2024-06-01", "2025-04-01", "2026-04-01"]  # ~annual labs


def main():
    app = create_app({"TESTING": True, "SECRET_KEY": "seed"})
    with app.app_context():
        from src.adapters.sqlite.patients_repo import PatientRepository
        from src.adapters.sqlite.vitals_repo import VitalsRepository
        from src.adapters.sqlite.flags_repo import ClinicalFlagsRepository
        pr, vr, fr = PatientRepository(), VitalsRepository(), ClinicalFlagsRepository()

        def S(pid, vtype, vals, dates):
            for d, v in zip(dates, vals):
                vr.add_reading(pid, vtype=vtype, value=round(v, 1),
                               measured_at=d + " 10:00:00", recorded_by="seed")

        # condition ids: 1=diabetes 2=hypertension 3=hyperlipidemia 4=ckd 5=thyroid
        created = 0
        for spec in PATIENTS:
            nid = spec["nid"]
            if pr.get_by_national_id(nid):
                print("skip (exists):", nid, spec["name"])
                continue
            pid = pr.create(national_id=nid, accounting_patient_id=None, full_name=spec["name"],
                            phone_number=spec["phone"], gender=spec["gender"],
                            birthdate=spec["birth"], address=None, enrolled_by="seed")
            for cid in spec["conditions"]:
                pr.add_condition(pid, cid)
            for k, v in spec.get("flags", {}).items():
                fr.set_flag(pid, k, v)
            for vt, (a, b, dates) in spec["vitals"].items():
                S(pid, vt, trend(a, b, len(dates)), dates)
            for mname, mclass, dose, start, change, stop in spec.get("meds", []):
                mid = pr.add_medication(pid, drug_name=mname, dose=dose, schedule=None,
                                        start_date=start, refill_due_date="2026-07-01",
                                        notes=None, drug_class=mclass, created_by="seed")
                if change:
                    pr.change_dose(mid, change[1], change_date=change[0], created_by="seed")
                if stop:
                    pr.stop_medication(mid, end_date=stop, created_by="seed")
            created += 1
            print("created:", nid, spec["name"], "pid=", pid)
        print(f"\nDone. {created} new demo patients.")


# value tuples are (start_value, end_value, dates)
PATIENTS = [
    dict(nid="TEST0001", name="نمونه ۱ - کنترل خوب", phone="09120000001", gender="male", birth="1975-03-10",
         conditions=[1], flags={},
         vitals={"hba1c": (7.2, 6.6, D6), "fbs": (140, 118, D12), "bp_systolic": (128, 124, D12),
                 "bp_diastolic": (82, 78, D12), "weight": (84, 81, D12)},
         meds=[("متفورمین", "metformin", "1000mg", "2024-06-15", None, None)]),

    dict(nid="TEST0002", name="نمونه ۲ - قند کنترل‌نشده رو به بهبود", phone="09120000002", gender="female", birth="1968-07-22",
         conditions=[1], flags={"hypo_risk": "low"},
         vitals={"hba1c": (9.6, 7.4, D6), "fbs": (220, 140, D12), "bp_systolic": (134, 128, D12),
                 "bp_diastolic": (86, 80, D12), "weight": (92, 86, D12)},
         meds=[("متفورمین", "metformin", "500mg", "2024-06-15", ("2024-10-01", "1000mg"), None),
               ("امپاگلیفلوزین", "sglt2i", "10mg", "2025-01-10", None, None)]),

    dict(nid="TEST0003", name="نمونه ۳ - دیابت+فشار+کلیه", phone="09120000003", gender="male", birth="1958-01-05",
         conditions=[1, 2, 4],
         flags={"ckd_stage_g": "G3b", "ckd_stage_a": "A3", "hypo_risk": "atrisk"},
         vitals={"hba1c": (8.4, 7.6, D6), "fbs": (180, 150, D12), "bp_systolic": (158, 134, D12),
                 "bp_diastolic": (94, 82, D12), "egfr": (52, 38, D3), "uacr": (180, 320, D3),
                 "weight": (88, 85, D12)},
         meds=[("متفورمین", "metformin", "1000mg", "2024-06-15", ("2025-04-10", "500mg"), None),
               ("لیزینوپریل", "acei", "10mg", "2024-06-15", None, None),
               ("داپاگلیفلوزین", "sglt2i", "10mg", "2024-09-01", None, None),
               ("فینرنون", "finerenone", "10mg", "2025-05-01", None, None)]),

    dict(nid="TEST0004", name="نمونه ۴ - دیابت+ASCVD", phone="09120000004", gender="male", birth="1962-11-30",
         conditions=[1, 3], flags={"ascvd": "1"},
         vitals={"hba1c": (8.0, 7.0, D6), "fbs": (165, 132, D12), "bp_systolic": (140, 126, D12),
                 "bp_diastolic": (88, 80, D12), "ldl": (150, 62, D3), "weight": (90, 84, D12)},
         meds=[("متفورمین", "metformin", "1000mg", "2024-06-15", None, None),
               ("سماگلوتاید", "glp1_ra", "1mg", "2024-08-01", None, None),
               ("آتورواستاتین", "statin", "40mg", "2024-06-15", None, None),
               ("آسپرین", "aspirin", "80mg", "2024-06-15", None, None)]),

    dict(nid="TEST0005", name="نمونه ۵ - دیابت+نارسایی قلب+چاقی", phone="09120000005", gender="female", birth="1965-05-18",
         conditions=[1], flags={"hf": "1", "hf_type": "HFpEF", "hf_symptomatic": "1"},
         vitals={"hba1c": (8.8, 7.2, D6), "fbs": (190, 138, D12), "bp_systolic": (136, 126, D12),
                 "bp_diastolic": (84, 78, D12), "bmi": (37, 31, D12), "weight": (104, 88, D12)},
         meds=[("داپاگلیفلوزین", "sglt2i", "10mg", "2024-06-20", None, None),
               ("تیرزپاتاید", "dual_gip_glp1", "5mg", "2024-09-01", ("2025-03-01", "10mg"), None)]),

    dict(nid="TEST0006", name="نمونه ۶ - چربی خون بالا", phone="09120000006", gender="female", birth="1972-09-09",
         conditions=[1, 3],
         vitals={"hba1c": (7.6, 7.0, D6), "fbs": (150, 128, D12), "ldl": (172, 78, D3),
                 "hdl": (38, 44, D3), "triglyceride": (240, 160, D3), "weight": (78, 75, D12)},
         meds=[("متفورمین", "metformin", "1000mg", "2024-06-15", None, None),
               ("رزوواستاتین", "statin", "20mg", "2024-07-01", ("2025-02-01", "40mg"), None)]),

    dict(nid="TEST0007", name="نمونه ۷ - سالمند فراژیل", phone="09120000007", gender="male", birth="1944-02-14",
         conditions=[1, 2], flags={"frailty": "complex", "hypo_risk": "high"},
         vitals={"hba1c": (8.2, 7.8, D6), "fbs": (160, 150, D12), "bp_systolic": (138, 132, D12),
                 "bp_diastolic": (80, 76, D12), "weight": (70, 68, D12)},
         meds=[("لیناگلیپتین", "dpp4i", "5mg", "2024-06-15", None, None),
               ("آملودیپین", "ccb", "5mg", "2024-06-15", None, None)]),

    dict(nid="TEST0008", name="نمونه ۸ - تحت انسولین، ریسک هیپو", phone="09120000008", gender="male", birth="1960-12-01",
         conditions=[1], flags={"hypo_risk": "high"},
         vitals={"hba1c": (9.0, 7.6, D6), "fbs": (200, 145, D12), "bp_systolic": (130, 126, D12),
                 "bp_diastolic": (80, 78, D12), "weight": (86, 88, D12)},
         meds=[("متفورمین", "metformin", "1000mg", "2024-06-15", None, None),
               ("گلارژین", "insulin_basal", "10U", "2024-07-01", ("2024-12-01", "22U"), None),
               ("گلی‌بنکلامید", "su", "5mg", "2024-06-15", None, "2025-01-15")]),

    dict(nid="TEST0009", name="نمونه ۹ - پیش‌دیابت", phone="09120000009", gender="female", birth="1980-06-25",
         conditions=[], flags={},
         vitals={"hba1c": (6.1, 5.9, D6), "fbs": (112, 104, D12), "bp_systolic": (124, 120, D12),
                 "bp_diastolic": (78, 76, D12), "bmi": (28, 26, D12), "weight": (76, 71, D12)},
         meds=[]),

    dict(nid="TEST0010", name="نمونه ۱۰ - دیابت+سیگاری+کبدچرب", phone="09120000010", gender="male", birth="1970-04-04",
         conditions=[1], flags={"smoking": "current", "masld": "1"},
         vitals={"hba1c": (8.6, 7.4, D6), "fbs": (185, 140, D12), "bp_systolic": (132, 128, D12),
                 "bp_diastolic": (84, 80, D12), "ldl": (140, 95, D3), "weight": (95, 89, D12)},
         meds=[("متفورمین", "metformin", "1000mg", "2024-06-15", None, None),
               ("سماگلوتاید", "glp1_ra", "0.5mg", "2024-10-01", ("2025-02-01", "1mg"), None)]),
]


if __name__ == "__main__":
    main()
