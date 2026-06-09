"""Messaging module (SMS): templates, campaigns, messages.

Provider is Mediana with a NullProvider fallback (docs/MASTER_PLAN.md); keys /
sending-number / message-type live per-tenant in clinic settings. Banned promo
words are rewritten by a compliance layer; patient wallet credit is the lawful
replacement for "discount/free". All tenant-owned.
"""

from django.db import models

from apps.common.models import TenantModel


class SmsTemplate(TenantModel):
    name = models.TextField()
    body = models.TextField()
    kind = models.TextField(blank=True, default="")  # reminder|recall|campaign|...
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "sms_template"
        indexes = [models.Index(fields=["clinic", "is_active"])]


class SmsCampaign(TenantModel):
    STATUS = [
        ("draft", "draft"),
        ("scheduled", "scheduled"),
        ("sending", "sending"),
        ("done", "done"),
        ("cancelled", "cancelled"),
    ]
    name = models.TextField()
    template = models.ForeignKey(
        SmsTemplate, on_delete=models.SET_NULL, related_name="+", null=True, blank=True
    )
    status = models.CharField(max_length=12, choices=STATUS, default="draft")
    scheduled_at = models.DateTimeField(null=True, blank=True)
    target_count = models.IntegerField(default=0)

    class Meta:
        db_table = "sms_campaign"
        indexes = [models.Index(fields=["clinic", "status"])]


class SmsMessage(TenantModel):
    STATUS = [
        ("queued", "queued"),
        ("sent", "sent"),
        ("delivered", "delivered"),
        ("failed", "failed"),
        ("simulated", "simulated"),  # NullProvider fallback
    ]
    campaign = models.ForeignKey(
        SmsCampaign, on_delete=models.SET_NULL, related_name="messages",
        null=True, blank=True,
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.SET_NULL, related_name="sms_messages",
        null=True, blank=True,
    )
    to_number = models.TextField()
    body = models.TextField()
    status = models.CharField(max_length=12, choices=STATUS, default="queued")
    provider_message_id = models.TextField(blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sms_message"
        indexes = [models.Index(fields=["clinic", "status", "-created_at"])]
