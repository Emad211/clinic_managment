"""
django-ninja API — halqe platform v1 (router wiring module).

This module stays intentionally thin: one shared ``NinjaAPI`` instance and one
router per bounded domain. Endpoint logic belongs in the domain modules.

Full endpoint surface (all under /api/v1, mounted from urls.py):

  auth        : POST /auth/login
  patients    : GET /patients, GET /patients/{uuid}, GET /patients/{uuid}/record
  vitals      : GET /patients/{uuid}/vitals/latest,
                POST /patients/{uuid}/vitals/{vital_id}/verify | /reject
  suggestions : GET /patients/{uuid}/suggestions,
                POST /patients/{uuid}/suggestions/{rule_code}/action,
                GET /patients/{uuid}/screening-timeline,
                GET /patients/{uuid}/medications/{med_id}/effect
  worklist    : GET /worklist, POST /worklist/{task_id}/done
  encounters  : POST/GET /patients/{uuid}/encounters,
                POST /encounters/{id}/vitals | /labs | /complete | /cancel | /prescriptions
  accounting  : patient/tariff/open-invoice projections, visit invoices,
                invoice detail/corrections, item payments, paid-only close,
                shift staff, nursing services, consumables and procedures
  manager     : GET /manager/{population-thresholds,suggestion-stats,
                cohort-outcomes,lapsed-return,control-trend}
  control-room: GET /control-room[/conversion | /cohort/{cohort_key}]
  doctor-queue: GET /doctor-queue, POST /doctor-queue/{invoice_id}/{start|done}
  engagement  : GET /engagement/approvals, POST .../{id}/{approve|reject|send}
  patient-card: GET /card/{token} (PUBLIC), POST /patients/{uuid}/card-token[/revoke]
  self-report : POST /patients/{uuid}/report-token, POST /patient-report/{token} (PUBLIC)
"""
from config.api_base import api, _jwt_auth, SYSTEM_TENANT_ID  # noqa: F401

from clinical.api.auth import router as auth_router
from clinical.api.patients import router as patients_router
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
from accounting_ops.api import router as accounting_router
from accounting_ops.payment_api import router as accounting_payment_router
from accounting_ops.nursing_api import router as accounting_nursing_router
from accounting_ops.procedure_api import router as accounting_procedure_router
from accounting_ops.invoice_workbench_api import router as accounting_workbench_router

# Only ``_MIN_N_FOR_RATE`` has a live config.api consumer.
from clinical.api.manager import _MIN_N_FOR_RATE  # noqa: F401

api.add_router("", auth_router)
api.add_router("", patients_router)
api.add_router("", vitals_router)
api.add_router("", suggestions_router)
api.add_router("", worklist_router)
api.add_router("", encounters_router)
api.add_router("", accounting_router)
api.add_router("", accounting_payment_router)
api.add_router("", accounting_nursing_router)
api.add_router("", accounting_procedure_router)
api.add_router("", accounting_workbench_router)
api.add_router("", control_room_router)
api.add_router("", doctor_queue_router)
api.add_router("", engagement_router)
api.add_router("/manager", manager_router)
api.add_router("", patient_card_router)
api.add_router("", self_report_router)
api.add_router("", allergies_router)
