"""Revenue analytics for the specialist clinic, sourced from the accounting DB
(read-only bridge). Revenue definition mirrors the accounting app exactly:
visits + injections + procedures from CLOSED invoices (consumables excluded).
"""
from datetime import datetime, timedelta

import jdatetime

from src.adapters.sqlite.core import get_db
from src.adapters import accounting_bridge
from src.common.utils import iran_now, format_jalali_date


def _jalali_month_start_gregorian() -> str:
    """Gregorian 'YYYY-MM-DD' of the first day of the current Jalali month."""
    j_today = jdatetime.date.fromgregorian(date=iran_now().date())
    g = jdatetime.date(j_today.year, j_today.month, 1).togregorian()
    return g.strftime('%Y-%m-%d')


# Campaign attribution window: a recipient's revenue is credited to a campaign only
# within this many days after their SMS (not "forever after send"). Bounds the
# last-touch over-attribution; could later become a manager-editable setting.
ATTRIBUTION_WINDOW_DAYS = 60


class RevenueService:

    def _enrolled_accounting_ids(self) -> list[int]:
        db = get_db()
        rows = db.execute(
            "SELECT accounting_patient_id FROM patient_links "
            "WHERE is_active=1 AND accounting_patient_id IS NOT NULL"
        ).fetchall()
        return [r['accounting_patient_id'] for r in rows]

    def _enrolled_pairs(self) -> list[tuple[int, str | None]]:
        """(accounting_patient_id, enrollment_date 'YYYY-MM-DD') for active linked patients.

        The enrollment date bounds specialist-office revenue: only accounting
        revenue on/after a patient joined the specialist office counts (earlier
        general-clinic visits are excluded).
        """
        db = get_db()
        rows = db.execute(
            "SELECT accounting_patient_id, enrolled_at FROM patient_links "
            "WHERE is_active=1 AND accounting_patient_id IS NOT NULL"
        ).fetchall()
        return [(r['accounting_patient_id'], (str(r['enrolled_at'])[:10] if r['enrolled_at'] else None))
                for r in rows]

    def dashboard(self) -> dict:
        """Top-level revenue + 30-day trend for enrolled patients.

        Specialist-office revenue counts each patient's accounting revenue only
        from their specialist enrollment date (`enrolled_at`) onward — visits made
        earlier in the general clinic (درمانگاه) are excluded.
        """
        if not accounting_bridge.is_available():
            return {'available': False}

        pairs = self._enrolled_pairs()
        total = accounting_bridge.revenue_for_enrolled(pairs)
        month = accounting_bridge.revenue_for_enrolled(pairs, floor=_jalali_month_start_gregorian())

        # 30-day trend (also bounded per-patient by enrollment date)
        today = iran_now().date()
        start = today - timedelta(days=29)
        daily = accounting_bridge.daily_revenue_for_enrolled(
            pairs, start.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d'))
        labels, values = [], []
        for i in range(30):
            d = start + timedelta(days=i)
            key = d.strftime('%Y-%m-%d')
            labels.append(format_jalali_date(key))
            values.append(daily.get(key, 0))

        campaigns = self.campaign_revenue()

        return {
            'available': True,
            'enrolled': len(pairs),
            'total': total,
            'month': month,
            'trend': {'labels': labels, 'values': values},
            'campaigns': campaigns,
        }

    def campaign_revenue(self, ids_hint: list[int] | None = None) -> dict:
        """Revenue attributed to each campaign = COLLECTED revenue from its
        accounting-linked recipients within ATTRIBUTION_WINDOW_DAYS after each
        recipient's SMS. This is a bounded last-touch correlation estimate (not a
        causal one — true lift needs a holdout/control group); the time window
        keeps it from ballooning as old, unrelated visits accumulate.
        """
        db = get_db()
        campaigns = db.execute(
            "SELECT id, name, campaign_type, credit_amount, sent_count FROM sms_campaigns ORDER BY id DESC"
        ).fetchall()

        rows_out = []
        attributed_total = 0
        credit_distributed = 0
        for c in campaigns:
            cid = c['id']
            # each accounting-linked recipient + when they were first sent this campaign
            # (GROUP BY per recipient — a bare MIN() without it collapsed to a single row)
            recs = db.execute(
                """SELECT pl.accounting_patient_id AS aid, MIN(m.sent_at) AS first_sent
                   FROM sms_messages m JOIN patient_links pl ON pl.id = m.patient_link_id
                   WHERE m.campaign_id = ? AND m.status='sent' AND pl.accounting_patient_id IS NOT NULL
                   GROUP BY pl.accounting_patient_id""",
                (cid,)).fetchall()
            triples = []
            for r in recs:
                if not r['aid'] or not r['first_sent']:
                    continue
                since = str(r['first_sent'])[:10]
                try:
                    until = (datetime.strptime(since, '%Y-%m-%d')
                             + timedelta(days=ATTRIBUTION_WINDOW_DAYS)).strftime('%Y-%m-%d')
                except ValueError:
                    continue
                triples.append((r['aid'], since, until))

            rev = accounting_bridge.revenue_windowed(triples) if triples else \
                {'billed': 0, 'collected': 0, 'invoices': 0}
            attributed_total += rev['collected']

            credit = db.execute(
                "SELECT COALESCE(SUM(amount),0) s FROM wallet_transactions WHERE reason='campaign' AND campaign_id=? AND amount>0",
                (cid,)).fetchone()['s']
            credit_distributed += int(credit or 0)

            rows_out.append({
                'id': cid, 'name': c['name'], 'type': c['campaign_type'],
                'recipients': len(triples), 'sent': c['sent_count'],
                'revenue': rev['collected'], 'invoices': rev['invoices'],
                'credit': int(credit or 0),
            })

        return {
            'rows': rows_out,
            'attributed_total': attributed_total,
            'credit_distributed': credit_distributed,
            'window_days': ATTRIBUTION_WINDOW_DAYS,
        }
