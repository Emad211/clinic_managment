"""Revenue analytics for the specialist clinic, sourced from the accounting DB
(read-only bridge). Revenue definition mirrors the accounting app exactly:
visits + injections + procedures from CLOSED invoices (consumables excluded).
"""
from datetime import timedelta

import jdatetime

from src.adapters.sqlite.core import get_db
from src.adapters import accounting_bridge
from src.common.utils import iran_now, format_jalali_date


def _jalali_month_start_gregorian() -> str:
    """Gregorian 'YYYY-MM-DD' of the first day of the current Jalali month."""
    j_today = jdatetime.date.fromgregorian(date=iran_now().date())
    g = jdatetime.date(j_today.year, j_today.month, 1).togregorian()
    return g.strftime('%Y-%m-%d')


class RevenueService:

    def _enrolled_accounting_ids(self) -> list[int]:
        db = get_db()
        rows = db.execute(
            "SELECT accounting_patient_id FROM patient_links "
            "WHERE is_active=1 AND accounting_patient_id IS NOT NULL"
        ).fetchall()
        return [r['accounting_patient_id'] for r in rows]

    def dashboard(self) -> dict:
        """Top-level revenue numbers + 30-day trend for enrolled patients."""
        if not accounting_bridge.is_available():
            return {'available': False}

        ids = self._enrolled_accounting_ids()
        total = accounting_bridge.revenue_for_accounting_ids(ids)
        month = accounting_bridge.revenue_for_accounting_ids(ids, since=_jalali_month_start_gregorian())

        # 30-day trend
        today = iran_now().date()
        start = today - timedelta(days=29)
        daily = accounting_bridge.daily_revenue_for_accounting_ids(
            ids, start.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d'))
        labels, values = [], []
        for i in range(30):
            d = start + timedelta(days=i)
            key = d.strftime('%Y-%m-%d')
            labels.append(format_jalali_date(key))
            values.append(daily.get(key, 0))

        campaigns = self.campaign_revenue(ids_hint=ids)

        return {
            'available': True,
            'enrolled': len(ids),
            'total': total,
            'month': month,
            'trend': {'labels': labels, 'values': values},
            'campaigns': campaigns,
        }

    def campaign_revenue(self, ids_hint: list[int] | None = None) -> dict:
        """Revenue attributed to each campaign = revenue from its recipients
        (in the accounting DB) on/after the campaign send date.
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
            # recipients of this campaign that are linked to accounting + send date
            recs = db.execute(
                """SELECT DISTINCT pl.accounting_patient_id AS aid, MIN(m.sent_at) AS first_sent
                   FROM sms_messages m JOIN patient_links pl ON pl.id = m.patient_link_id
                   WHERE m.campaign_id = ? AND m.status='sent' AND pl.accounting_patient_id IS NOT NULL""",
                (cid,)).fetchall()
            aids = [r['aid'] for r in recs if r['aid']]
            send_dates = [r['first_sent'] for r in recs if r['first_sent']]
            since = min(send_dates)[:10] if send_dates else None

            rev = accounting_bridge.revenue_for_accounting_ids(aids, since=since) if aids else \
                {'total': 0, 'invoices': 0}
            attributed_total += rev['total']

            credit = db.execute(
                "SELECT COALESCE(SUM(amount),0) s FROM wallet_transactions WHERE reason='campaign' AND campaign_id=? AND amount>0",
                (cid,)).fetchone()['s']
            credit_distributed += int(credit or 0)

            rows_out.append({
                'id': cid, 'name': c['name'], 'type': c['campaign_type'],
                'recipients': len(aids), 'sent': c['sent_count'],
                'revenue': rev['total'], 'invoices': rev.get('invoices', 0),
                'credit': int(credit or 0),
            })

        return {
            'rows': rows_out,
            'attributed_total': attributed_total,
            'credit_distributed': credit_distributed,
        }
