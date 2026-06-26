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
#
# SYSTEM_TENANT_ID is re-exported here so that existing
# `from config.api import SYSTEM_TENANT_ID` consumers (e.g.
# tests/test_tenant_context.py) keep working unchanged.
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

# ---------------------------------------------------------------------------
# Test-facing re-exports.  No endpoint/schema/helper is defined in this module
# any more, so these re-exports keep the public `config.api` import surface
# stable for tests and any indirect consumer (same noqa pattern throughout).
# ---------------------------------------------------------------------------
# tests/test_suggestion_events.py: `from config.api import _MIN_N_FOR_RATE`
from clinical.api.manager import _MIN_N_FOR_RATE  # noqa: F401  (re-export)
# Cross-domain helper now lives in clinical.api._shared; re-export here so any
# `from config.api import _resolve_patient_link_for_tenant` consumer keeps working.
from clinical.api._shared import _resolve_patient_link_for_tenant  # noqa: F401  (re-export)
# Patient-card / self-report test-facing symbols (cleanup step 6).
from clinical.api.patient_card import (  # noqa: F401  (re-export)
    PublicCardResponse,
    VitalCardDTO,
    CardTokenOut,
    get_public_card,
    issue_card_token,
    revoke_card_token,
    _card_allow,
)
from clinical.api.self_report import (  # noqa: F401  (re-export)
    ReportTokenOut,
    SelfReportIn,
    SelfReportOut,
    issue_report_token,
    submit_patient_report,
    _check_rate_limit,
    _REPORT_ALLOWED_TYPES,
)

# ---------------------------------------------------------------------------
# Router wiring.  Every router uses prefix "" except manager (prefix "/manager")
# so that /api/v1 (urls.py) + prefix + the route's own path == the same full
# paths as before the split — byte-identical, with auth/permission unchanged.
# ---------------------------------------------------------------------------
# auth domain: route "/auth/login"; prefix "" → /api/v1/auth/login.
api.add_router("", auth_router)
# patients domain (step 7): routes "/patients", "/patients/{uuid}",
# "/patients/{uuid}/record"; prefix "" keeps them byte-identical.
api.add_router("", patients_router)
# vitals domain (step 7): "/patients/{uuid}/vitals/latest" + vital-review
# (.../verify | .../reject). SACRED: the 6 verified=True engine filters are
# untouched — only the endpoints moved.
api.add_router("", vitals_router)
# suggestions domain (step 7): suggestions list + action + screening-timeline +
# medication effect. Suggestion-only framing preserved verbatim.
api.add_router("", suggestions_router)
# worklist domain (step 7): "/worklist" + "/worklist/{task_id}/done". The
# manager-only revenue gate on include_revenue is preserved verbatim.
api.add_router("", worklist_router)
# encounters domain (step 7): encounter write-path + free-mode prescriptions.
# BLOCKED: mode='insurance' still returns 422 (insurance/MV3 track blocked).
api.add_router("", encounters_router)
# control-room domain (step 4): "/control-room…"; prefix "" keeps the conversion
# and cohort/{cohort_key} sub-paths byte-identical.
api.add_router("", control_room_router)
# doctor-queue domain (step 4): "/doctor-queue…"; prefix "" keeps /start | /done.
api.add_router("", doctor_queue_router)
# engagement domain (step 4): "/engagement/approvals…"; prefix "" keeps the
# list + approve | reject | send sub-paths byte-identical.
api.add_router("", engagement_router)
# manager analytics domain (step 5): router routes carry short sub-paths and the
# prefix "/manager" reassembles /api/v1/manager/… byte-identical.
api.add_router("/manager", manager_router)
# patient-card domain (step 6): "/card/{token}", "/patients/{uuid}/card-token",
# ".../card-token/revoke". SACRED: GET /card/{token} stays auth=None (public).
api.add_router("", patient_card_router)
# self-report domain (step 6): "/patients/{uuid}/report-token" +
# "/patient-report/{token}". SACRED: POST /patient-report/{token} stays
# auth=None (public, one-time token).
api.add_router("", self_report_router)
