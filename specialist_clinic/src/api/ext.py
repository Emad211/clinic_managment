"""Token-authenticated bridge blueprint for the prescription browser extension.

This blueprint is NOT session/cookie based — it is called from the doctor's MV3
browser extension running on insurance web panels (e.g. ep.tamin.ir). Each request
carries the physician's extension API token (issued from Manager → Users) in an
`Authorization: Bearer` header (SECU-05: never a ?token= query param — that would leak
into logs/history). The token maps to an active, unexpired user row.

  GET  /api/ext/pending   → open REMOTE follow-ups awaiting a periodic Rx,
                            each with the patient's national_id + active meds.
  POST /api/ext/captured  → record a captured insurance prescription against a
                            patient (by national_id) and close the linked follow-up.
"""
from flask import Blueprint, request, jsonify

from src.adapters.sqlite.core import get_db

bp = Blueprint("ext", __name__, url_prefix="/api/ext")

# Only the insurance web panels (and localhost during dev) may call this bridge.
ALLOWED_ORIGINS = ('https://ep.tamin.ir', 'http://localhost', 'http://127.0.0.1')


def _origin_allowed(origin: str) -> bool:
    if not origin:
        return False
    return any(origin == o or origin.startswith(o) for o in ALLOWED_ORIGINS)


def _user_from_request():
    """Resolve the calling physician from the extension API token, or None.
    SECU-05: the token is accepted ONLY via the `Authorization: Bearer` header — never a
    `?token=` query param (leaks into server logs / browser history / Referer) nor the body."""
    auth = request.headers.get('Authorization', '')
    token = auth[7:].strip() if auth.lower().startswith('bearer ') else ''
    from src.adapters.sqlite.auth_repo import AuthRepository
    return AuthRepository().get_user_by_token(token) if token else None


@bp.after_request
def _cors(response):
    origin = request.headers.get('Origin', '')
    if _origin_allowed(origin):
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response


@bp.route("/pending", methods=["GET", "OPTIONS"])
def pending():
    """Open REMOTE follow-ups awaiting a periodic prescription, with the patient's
    national_id and active medications so the extension can auto-fill the panel."""
    if request.method == "OPTIONS":
        return ('', 204)
    user = _user_from_request()
    if not user:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401

    db = get_db()
    rows = db.execute(
        """SELECT f.id AS followup_id, p.id AS patient_link_id, p.national_id, p.full_name
           FROM followup_tasks f JOIN patient_links p ON p.id=f.patient_link_id
           WHERE f.status='open' AND f.fulfillment='remote'
           ORDER BY f.due_date IS NULL, f.due_date
           LIMIT 200""").fetchall()
    items = []
    for r in rows:
        r = dict(r)
        meds = db.execute(
            "SELECT drug_name, dose, schedule FROM patient_medications "
            "WHERE patient_link_id=? AND is_active=1", (r['patient_link_id'],)).fetchall()
        r['medications'] = [dict(m) for m in meds]
        items.append(r)
    return jsonify({'items': items})


@bp.route("/captured", methods=["POST", "OPTIONS"])
def captured():
    """Record a captured insurance prescription (by patient national_id) and, when a
    follow-up task id is supplied, close that remote follow-up."""
    if request.method == "OPTIONS":
        return ('', 204)
    user = _user_from_request()
    if not user:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    db = get_db()
    row = db.execute(
        "SELECT id FROM patient_links WHERE national_id=?", (data.get('national_id'),)).fetchone()
    if not row:
        return jsonify({'ok': False, 'error': 'patient_not_found'}), 404

    from src.adapters.sqlite.record_repo import RecordRepository
    rx_id = RecordRepository().add_prescription(
        row['id'], kind='refill', items=data.get('items'), mode='insurance',
        insurer=data.get('insurer'), portal_rx_id=data.get('portal_rx_id'),
        prescriber_user_id=user['id'], followup_task_id=data.get('followup_task_id'))

    if data.get('followup_task_id'):
        from src.adapters.sqlite.followups_repo import FollowupRepository
        FollowupRepository().resolve(
            int(data['followup_task_id']), 'done', call_log='نسخهٔ بیمه‌ای از پل ثبت شد')

    return jsonify({'ok': True, 'prescription_id': rx_id})
