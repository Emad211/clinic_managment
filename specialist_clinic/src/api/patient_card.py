"""Public patient-card Channel (ADR-0004).

A token-addressed, READ-ONLY view of a patient's own latest vitals + next appointment.
There is NO session / login: the page is addressed solely by an unguessable per-patient
token (issued by staff). The blueprint is GET-only **by construction** and calls ONLY the
read-only `card_projection_service` — it never writes. Gated by the
`patient_card_enabled` setting (default off) so the shipped .exe doesn't expose the
surface until the clinic turns it on. A guard test (tests/test_patient_card.py) asserts
the GET-only + zero-write invariants.

Delivery (ADR-0004 §4): the IN-CLINIC path (QR/tablet on the clinic LAN) works today. The
INTERNET path (SMS link to the patient's phone) stays blocked until an Iranian VPS +
WireGuard relay (TLS) and Kavenegar KYC are in place.
"""
from flask import Blueprint, render_template, abort

from src.adapters.sqlite.sms_repo import SmsRepository
from src.services.card_projection_service import card_for_token

bp = Blueprint("patient_card", __name__, url_prefix="/card")


def _enabled() -> bool:
    return SmsRepository().get_setting('patient_card_enabled', '0') == '1'


@bp.route("/<token>", methods=["GET"])
def view(token):
    if not _enabled():
        abort(404)
    data = card_for_token(token)
    if data is None:
        # Generic 404 — never reveal whether the token existed, expired, or was revoked.
        abort(404)
    return render_template("card/public_card.html", **data)
