"""
Management command: seed_engagement_events

Seeds the default event→channel routing catalog into clinical.engagement_events.

Source of truth: specialist_clinic/src/adapters/sqlite/schema.sql
  `INSERT OR IGNORE INTO engagement_events` block (lines 275-293).

All rows are ported FAITHFULLY — event_key, label (Persian), category, channel,
sms_template, lead_days, cooldown_days, source_action, priority — copied verbatim
from the source.  Fields that are not in the SQLite INSERT (event_type, is_custom,
notes) use schema defaults (NULL / FALSE / NULL).

Idempotent: ON CONFLICT (tenant_id, event_key) DO NOTHING — manager edits to
existing rows are preserved.  A --force-update flag is provided for CI/reset use.

Usage:
    python manage.py seed_engagement_events
    python manage.py seed_engagement_events --tenant-id 2
    python manage.py seed_engagement_events --force-update
"""
from django.core.management.base import BaseCommand


# ---------------------------------------------------------------------------
# Default event catalog — ported faithfully from:
#   specialist_clinic/src/adapters/sqlite/schema.sql
#   `INSERT OR IGNORE INTO engagement_events` block
#
# Each tuple: (event_key, label, category, channel, sms_template,
#              lead_days, cooldown_days, source_action, priority)
# NULL is used for fields not provided in the source INSERT (they'll use the
# schema DEFAULT values: event_type=NULL, is_custom=FALSE, notes=NULL,
# is_active=TRUE).
# ---------------------------------------------------------------------------
_DEFAULT_EVENTS = [
    (
        "appointment_reminder",
        "یادآوری نوبت",
        "operational",
        "sms",
        "سلام {name} عزیز، یادآوری نوبت شما در کلینیک تخصصی. لطفاً در زمان مقرر مراجعه فرمایید.",
        1,    # lead_days
        1,    # cooldown_days
        None, # source_action
        10,   # priority
    ),
    (
        "refill_due",
        "یادآوری تجدید دارو",
        "operational",
        "sms",
        "سلام {name} عزیز، داروی شما رو به اتمام است. جهت تمدید نسخه با کلینیک تماس بگیرید.",
        7,
        25,
        None,
        20,
    ),
    (
        "monitoring_due",
        "سررسید آزمایش پایش",
        "clinical",
        "sms",
        "سلام {name} عزیز، زمان آزمایشِ پایشِ دوره‌ای شما فرارسیده است. لطفاً نوبت بگیرید.",
        0,
        60,
        "create_followup",
        30,
    ),
    (
        "screening_due",
        "سررسید غربالگری",
        "clinical",
        "sms",
        "سلام {name} عزیز، زمان غربالگریِ دوره‌ای شما فرارسیده است. برای حفظ سلامتی نوبت بگیرید.",
        0,
        180,
        "schedule_screening",
        40,
    ),
    (
        "vaccine_due",
        "سررسید واکسن",
        "clinical",
        "sms",
        "سلام {name} عزیز، یک واکسنِ توصیه‌شده برای شما سررسید شده است. لطفاً با کلینیک هماهنگ کنید.",
        0,
        180,
        "vaccine",
        50,
    ),
    (
        "lapsed",
        "بدون مراجعه اخیر",
        "clinical",
        "both",
        "سلام {name} عزیز، مدتی است شما را در کلینیک ندیده‌ایم. برای ادامهٔ مراقبت نوبت بگیرید.",
        0,
        60,
        None,
        60,
    ),
    (
        "uncontrolled",
        "کنترل‌نشده",
        "clinical",
        "worklist",
        None,
        0,
        14,
        None,
        70,
    ),
    (
        "red_flag",
        "هشدار فوری بالینی",
        "clinical",
        "worklist",
        None,
        0,
        1,
        "redflag",
        80,
    ),
    (
        "visit_invite",
        "دعوت به نوبت (پیامکی)",
        "operational",
        "sms",
        "سلام {name} عزیز، برای ادامهٔ روند درمان لطفاً جهت تعیینِ نوبتِ ویزیت با کلینیک تماس بگیرید.",
        0,
        7,
        None,
        15,
    ),
    (
        "thank_you",
        "تشکر پس از مراجعه",
        "operational",
        "sms",
        "سلام {name} عزیز، از مراجعه و اعتمادِ شما به کلینیک سپاسگزاریم. سلامت و تندرست باشید.",
        0,
        1,
        None,
        16,
    ),
    (
        "ear_wash_invite",
        "پیگیریِ شستشوی گوش",
        "operational",
        "sms",
        "سلام {name} عزیز، جهتِ پیگیریِ شستشوی گوش در صورتِ نیاز با کلینیک هماهنگ کنید. اگر درد، ترشح یا کاهشِ شنوایی داشتید زودتر تماس بگیرید.",
        0,
        30,
        None,
        17,
    ),
    (
        "wound_care_invite",
        "دعوتِ پانسمان/کشیدن بخیه",
        "operational",
        "sms",
        "سلام {name} عزیز، برای تعویضِ پانسمان یا کشیدنِ بخیه لطفاً طبقِ زمانِ توصیه‌شدهٔ پزشک مراجعه کنید. برای هماهنگیِ نوبت تماس بگیرید.",
        0,
        30,
        None,
        18,
    ),
    (
        "lab_consult_invite",
        "دعوتِ آزمایش و مشاوره",
        "operational",
        "sms",
        "سلام {name} عزیز، طبقِ توصیهٔ پزشک برای انجامِ آزمایش و مشاورهٔ پیگیری لطفاً جهتِ تعیینِ نوبت با کلینیک تماس بگیرید.",
        0,
        14,
        None,
        19,
    ),
    (
        "bp_glucose_invite",
        "یادآوریِ قند و فشار",
        "operational",
        "sms",
        "سلام {name} عزیز، برای اندازه‌گیریِ دوره‌ایِ قند و فشارِ خون لطفاً جهتِ هماهنگیِ نوبت با کلینیک تماس بگیرید.",
        0,
        14,
        None,
        19,
    ),
]


def _build_conninfo(conf: dict) -> str:
    """Build a psycopg conninfo string from Django DATABASES settings dict."""
    parts = []
    for django_key, pg_key in [
        ("NAME", "dbname"),
        ("USER", "user"),
        ("PASSWORD", "password"),
        ("HOST", "host"),
        ("PORT", "port"),
    ]:
        v = conf.get(django_key)
        if v:
            parts.append(f"{pg_key}='{str(v).replace(chr(39), chr(92)+chr(39))}'")
    return " ".join(parts)


class Command(BaseCommand):
    help = (
        "Seed default engagement events into clinical.engagement_events. "
        "Idempotent (ON CONFLICT DO NOTHING by default — preserves manager edits)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant-id",
            type=int,
            default=1,
            help="Tenant ID to seed events for (default: 1).",
        )
        parser.add_argument(
            "--force-update",
            action="store_true",
            default=False,
            help=(
                "If set, UPDATE existing rows (clobbers manager edits). "
                "Default: DO NOTHING on conflict — preserves manager edits."
            ),
        )

    def handle(self, *args, **options):
        tenant_id: int = options["tenant_id"]
        force_update: bool = options["force_update"]
        verbosity: int = options.get("verbosity", 1)

        import psycopg
        from django.conf import settings

        conninfo = _build_conninfo(settings.DATABASES["default"])

        inserted = 0
        updated = 0
        skipped = 0

        with psycopg.connect(conninfo, autocommit=True) as conn:
            # RLS (slice5): ست کردنِ GUC قبل از هر INSERT/UPDATE
            # تضمین می‌کند tenant_isolation WITH CHECK رد نشود.
            conn.execute(
                "SELECT set_config('app.current_tenant', %s, false)",
                [str(tenant_id)],
            )
            for (
                event_key,
                label,
                category,
                channel,
                sms_template,
                lead_days,
                cooldown_days,
                source_action,
                priority,
            ) in _DEFAULT_EVENTS:
                if force_update:
                    conn.execute(
                        """
                        INSERT INTO clinical.engagement_events
                            (tenant_id, event_key, label, category, channel,
                             sms_template, lead_days, cooldown_days,
                             source_action, priority, is_active)
                        VALUES
                            (%(tid)s, %(key)s, %(label)s, %(cat)s, %(chan)s,
                             %(tmpl)s, %(lead)s, %(cool)s,
                             %(src)s, %(pri)s, TRUE)
                        ON CONFLICT (tenant_id, event_key) DO UPDATE
                            SET label         = EXCLUDED.label,
                                category      = EXCLUDED.category,
                                channel       = EXCLUDED.channel,
                                sms_template  = EXCLUDED.sms_template,
                                lead_days     = EXCLUDED.lead_days,
                                cooldown_days = EXCLUDED.cooldown_days,
                                source_action = EXCLUDED.source_action,
                                priority      = EXCLUDED.priority,
                                is_active     = TRUE
                        """,
                        {
                            "tid": tenant_id,
                            "key": event_key,
                            "label": label,
                            "cat": category,
                            "chan": channel,
                            "tmpl": sms_template,
                            "lead": lead_days,
                            "cool": cooldown_days,
                            "src": source_action,
                            "pri": priority,
                        },
                    )
                    updated += 1
                else:
                    result = conn.execute(
                        """
                        INSERT INTO clinical.engagement_events
                            (tenant_id, event_key, label, category, channel,
                             sms_template, lead_days, cooldown_days,
                             source_action, priority, is_active)
                        VALUES
                            (%(tid)s, %(key)s, %(label)s, %(cat)s, %(chan)s,
                             %(tmpl)s, %(lead)s, %(cool)s,
                             %(src)s, %(pri)s, TRUE)
                        ON CONFLICT (tenant_id, event_key) DO NOTHING
                        """,
                        {
                            "tid": tenant_id,
                            "key": event_key,
                            "label": label,
                            "cat": category,
                            "chan": channel,
                            "tmpl": sms_template,
                            "lead": lead_days,
                            "cool": cooldown_days,
                            "src": source_action,
                            "pri": priority,
                        },
                    )
                    if result.rowcount > 0:
                        inserted += 1
                    else:
                        skipped += 1

        if verbosity >= 1:
            if force_update:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Done. {len(_DEFAULT_EVENTS)} events upserted (force-update) "
                        f"for tenant={tenant_id}."
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Done. {inserted} inserted, {skipped} already existed "
                        f"(skipped) for tenant={tenant_id}."
                    )
                )
