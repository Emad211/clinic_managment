"""
Management command: generate_suggestion_fire_events

برای هر بیمارِ فعالِ tenant، به‌ازایِ هر rule_code که suggestion_log آن 'pending' است،
یک ردیفِ fired_daily در clinical.suggestion_events درج می‌کند — حداکثر یک بار در روز
per (tenant, patient_link, rule_code) (dedup با NOT EXISTS).

کاربرد:
    python manage.py generate_suggestion_fire_events
    python manage.py generate_suggestion_fire_events --tenant-id 2

زمان‌بندی خودکار موکولِ قدمِ ۵۱ است. این command همین‌الان قابلِ اجرا است.
برایِ تولید: با وقتِ ایران (iran_now) می‌دوید؛ occurred_at را صریحاً ست می‌کند.

idempotent: اجرایِ دوباره در یک روز ردیفِ تکراری نمی‌سازد.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Insert fired_daily events into suggestion_events for all pending "
        "suggestion_log rows. One row per (tenant, patient_link, rule_code) "
        "per day. Idempotent — safe to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant-id",
            type=int,
            default=1,
            help="Tenant ID to process (default: 1).",
        )

    def handle(self, *args, **options):
        tenant_id: int = options["tenant_id"]
        verbosity: int = options.get("verbosity", 1)

        if verbosity >= 1:
            self.stdout.write(
                self.style.NOTICE(
                    f"Generating fired_daily suggestion events for tenant={tenant_id} ..."
                )
            )

        from django.db import connection
        from django.utils import timezone

        # occurred_at: ISO UTC (بک‌اند ISO — تبدیلِ نمایشی در لایهٔ UI).
        now_utc = timezone.now()

        # INSERT ... SELECT ... WHERE NOT EXISTS (dedup per day per (tenant,patient,rule)).
        # از raw SQL استفاده می‌کنیم چون NOT EXISTS روی جدولِ دیگر است و
        # Django ORM برایِ این pattern طولانی است.
        sql = """
            INSERT INTO clinical.suggestion_events
                (tenant_id, patient_link_id, rule_code, event_type,
                 acted_by, suggestion_text, evidence_level, note, occurred_at)
            SELECT
                sl.tenant_id,
                sl.patient_link_id,
                sl.rule_code,
                'fired_daily',
                NULL,                -- acted_by: NULL for fired_daily
                sl.suggestion_text,
                sl.evidence_level,
                NULL,                -- note: NULL for fired_daily
                %(now_utc)s
            FROM clinical.suggestion_log sl
            WHERE sl.tenant_id = %(tenant_id)s
              AND sl.status = 'pending'
              AND NOT EXISTS (
                SELECT 1
                FROM clinical.suggestion_events se
                WHERE se.tenant_id        = sl.tenant_id
                  AND se.patient_link_id  = sl.patient_link_id
                  AND se.rule_code        = sl.rule_code
                  AND se.event_type       = 'fired_daily'
                  AND DATE(se.occurred_at) = CURRENT_DATE
              )
        """

        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, {"tenant_id": tenant_id, "now_utc": now_utc})
                inserted = cursor.rowcount
        except Exception as exc:
            self.stderr.write(
                self.style.ERROR(
                    f"generate_suggestion_fire_events failed for tenant={tenant_id}: {exc}"
                )
            )
            raise

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Inserted {inserted} fired_daily event(s) for tenant={tenant_id}."
            )
        )

        if verbosity >= 2 and inserted == 0:
            self.stdout.write(
                self.style.NOTICE(
                    "  0 rows inserted — all pending suggestions already have a "
                    "fired_daily event today, or no pending suggestions exist."
                )
            )
