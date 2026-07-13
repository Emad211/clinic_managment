"""
django-ninja API — halqe platform v1 (router wiring module).

This module is intentionally thin: it imports the shared ``NinjaAPI`` instance
and domain routers, then wires each router without changing its URL bytes.

Endpoint surface (all under /api/v1):

  auth          : POST /auth/login
  patients      : GET /patients, /patients/{uuid}, /patients/{uuid}/record
  patient-record: GET /patients/{uuid}/record-data plus structured record CRUD
  vitals        : latest + physician verify/reject
  suggestions   : suggestions, actions, screening timeline, medication effect
  worklist      : list + done
  encounters    : encounter/vital/lab/prescription write path
  manager       : descriptive analytics endpoints
  control-room  : cohort targeting views
  doctor-queue  : waiting/in-progress/done
  engagement    : approval queue
  patient-card  : public card + token administration
  self-report   : public one-time report submit
"""
from config.api_base import api, _jwt_auth, SYSTEM_TENANT_ID  # noqa: F401

from clinical.api.auth import router as auth_router
from clinical.api.patients import router as patients_router
from clinical.api.record_data import router as record_data_router
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

# Stable test-facing re-export.
from clinical.api.manager import _MIN_N_FOR_RATE  # noqa: F401

api.add_router("", auth_router)
api.add_router("", patients_router)
api.add_router("", record_data_router)
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
