"""
django-ninja API — halqe platform v1 (router wiring module).

As of cleanup step 7 this module is THIN: it imports the shared ``NinjaAPI``
instance from ``config.api_base`` and every domain ``Router`` from
``clinical.api.<domain>``, wires each router onto ``api`` with
``api.add_router(prefix, router)`` (preserving every URL byte-for-byte), and
re-exports the handful of test-facing symbols that consumers import via
``from config.api import …``. No endpoint, schema or helper is defined here any
more — they all live in their domain routers (or ``clinical.api._shared`` for
cross-domain helpers/DTOs).

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
  accounting  : GET patient/tariff/open-invoice projections,
                POST /accounting/invoices/visit | /{id}/close
  manager     : GET /manager/{population-thresholds,suggestion-stats,
                cohort-outcomes,lapsed-return,control-trend}
  control-room: GET /control-room[/conversion | /cohort/{cohort_key}]
  doctor-queue: GET /doctor-queue, POST /doctor-queue/{invoice_id}/{start|done}
  engagement  : GET /engagement/approvals, POST .../{id}/{approve|reject|send}
  patient-card: GET /card/{token} (PUBLIC), POST /patients/{uuid}/card-token[/revoke]
  self-report : POST /patients/{uuid}/report-token, POST /patient-report/{token} (PUBLIC)
"""
# ---------------------------------------------------------------------------
# Shared API base — the single NinjaAPI instance, JWT auth dependency, the
# Http404 exception handler and the SYSTEM_TENANT_ID sentinel live in
# config.api_base (cleanup step 3).
# ---------------------------------------------------------------------------
from config.api_base import api, _jwt_auth, SYSTEM_TENANT_ID  # noqa: F401  (re-export)

# ---------------------------------------------------------------------------
# Domain routers.  Each is wired below with add_router using a prefix that keeps
# the full URL byte-identical to the pre-split paths.
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Test-facing re-exports. Only ``_MIN_N_FOR_RATE`` has a live config.api consumer.
# ---------------------------------------------------------------------------
from clinical.api.manager import _MIN_N_FOR_RATE  # noqa: F401  (re-export)

# ---------------------------------------------------------------------------
# Router wiring. Every router uses prefix "" except manager (prefix "/manager").
# ---------------------------------------------------------------------------
api.add_router("", auth_router)
api.add_router("", patients_router)
api.add_router("", vitals_router)
api.add_router("", suggestions_router)
api.add_router("", worklist_router)
api.add_router("", encounters_router)
api.add_router("", accounting_router)
api.add_router("", control_room_router)
api.add_router("", doctor_queue_router)
api.add_router("", engagement_router)
api.add_router("/manager", manager_router)
api.add_router("", patient_card_router)
api.add_router("", self_report_router)
api.add_router("", allergies_router)
