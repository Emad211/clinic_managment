import pytest

from apps.chronic.models import FollowupTask
from apps.messaging.models import SmsMessage

pytestmark = pytest.mark.django_db


def test_worklist_renders(auth_client, followup):
    r = auth_client.get("/worklist/")
    assert r.status_code == 200 and "کارتابل پیگیری" in r.content.decode()


def test_followup_mark_done(auth_client, followup):
    auth_client.post(f"/followups/{followup.id}/done/")
    followup.refresh_from_db()
    assert followup.status == "done" and followup.handled_at is not None
    assert FollowupTask.objects.filter(status="open").count() == 0


def test_followup_sms_reminder(auth_client, followup):
    auth_client.post(f"/followups/{followup.id}/remind/")
    msgs = SmsMessage.objects.filter(patient=followup.patient)
    assert msgs.count() == 1
    assert "یادآوری" in msgs.first().body and msgs.first().status == "simulated"
