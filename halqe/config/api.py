"""
django-ninja API — halqe platform v1 (router wiring module).

This module is intentionally thin: it imports the shared ``NinjaAPI`` instance,
registers one router per domain, and keeps endpoint logic inside the domain.
"""
from config.api_base import api, _jwt_auth, SYSTEM_TENANT_ID  # noqa: F401

from clinical.api.auth import router as auth_router
from clinical.api.patients import router as patients_router
from clinical.api.patient_record import router as patient_record_router
from clinical.api.vitals import router as vitals_router
from clinical.api.suggestions import router as suggestions_router
from clinical.api.worklist import router as worklist_router
from clinical.api.encounters import router as encounters_router
from clinical.api.control_room import router as control_room_router
from clinical.api.doctor_queue import router as doctor_queue_router
from clinical.api.engagement import router as engagement_router
from clinical.api.manager import router as manager_router
from clinical.api.patient_card import router as patient_card_router
from clinical.api.self_report import router as self_report_router
from clinical.api.allergies import router as allergies_router

# tests/test_suggestion_events.py imports this compatibility symbol.
from clinical.api.manager import _MIN_N_FOR_RATE  # noqa: F401

api.add_router("", auth_router)
api.add_router("", patients_router)
api.add_router("", patient_record_router)
api.add_router("", vitals_router)
api.add_router("", suggestions_router)
api.add_router("", worklist_router)
api.add_router("", encounters_router)
api.add_router("", control_room_router)
api.add_router("", doctor_queue_router)
api.add_router("", engagement_router)
api.add_router("/manager", manager_router)
api.add_router("", patient_card_router)
api.add_router("", self_report_router)
api.add_router("", allergies_router)
