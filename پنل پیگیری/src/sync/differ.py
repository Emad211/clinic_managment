"""Mirror differ: applies one poll snapshot to the acc_* tables and emits domain events.

Runs inside one panel-DB transaction, *after* the accounting connection is
closed (docs/02 §5). Idempotent: applying the same snapshot twice changes
nothing the second time and emits no events.

For every invoice in ``snap.item_invoice_ids`` the snapshot holds *all* of its
items and payments, so anything the mirror has for that invoice but the
snapshot does not was deleted in accounting (docs/03 §8).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from ..adapters.accounting.reader import PollSnapshot
from ..adapters.sqlite import mirror_repo as repo
from ..adapters.sqlite.mirror_repo import MirrorItem
from ..domain import categories as cat
from ..domain.events import (DomainEvent, InvoiceClosed, ItemAdded, ItemDeleted, ItemPaid, PatientChanged,
                             PaymentRemoved)
from ..domain.identity import identity_ok


@dataclass
class DiffResult:
    events: list[DomainEvent] = field(default_factory=list)
    invoices_seen: int = 0
    items_seen: int = 0


def mirror_items(snap: PollSnapshot) -> list[MirrorItem]:
    out = [MirrorItem("visit", v.id, v.invoice_id, v.patient_id, None, None, v.doctor_id, None, None,
                      v.price, v.work_date, v.shift, v.visit_date) for v in snap.visits]
    out += [MirrorItem("injection", i.id, i.invoice_id, i.patient_id, i.injection_type, i.service_id,
                       i.doctor_id, i.nurse_id, None, i.total_price, i.work_date, None, None)
            for i in snap.injections]
    out += [MirrorItem("procedure", p.id, p.invoice_id, p.patient_id, p.procedure_type, None,
                       p.doctor_id, p.nurse_id, p.performer_type, p.price, p.work_date, None, None)
            for p in snap.procedures]
    return out


def _categories(it: MirrorItem, ids: cat.ServiceIds, proc_map: dict[str, str | None]) -> set[str]:
    if it.item_type == "visit":
        return {cat.VISIT}
    if it.item_type == "injection":
        return cat.injection_categories(it.service_id, it.raw_name, ids)
    return cat.procedure_categories(it.raw_name, proc_map)


def apply_snapshot(conn: sqlite3.Connection, snap: PollSnapshot, ids: cat.ServiceIds, now: str) -> DiffResult:
    result = DiffResult()
    read_ids = set(snap.item_invoice_ids)
    invoices = {inv.id: inv for inv in (*snap.watched_invoices, *snap.new_invoices)}

    # Invoices
    prev_status = repo.invoice_statuses(conn, read_ids)
    for iid in sorted(read_ids):
        inv = invoices.get(iid)
        if inv is None:
            if prev_status.get(iid) not in (None, "missing"):
                repo.mark_invoice_missing(conn, iid, now)
            continue
        repo.upsert_invoice(conn, inv, now)
        result.invoices_seen += 1
        if inv.status == "closed" and prev_status.get(iid) != "closed":
            result.events.append(InvoiceClosed(iid, inv.total_amount))

    # Items, categories, payments
    proc_map = repo.procedure_category_map(conn)
    prev_items = repo.item_states(conn, read_ids)
    payments = {(p.item_type, p.item_id): p for p in snap.payments}
    current = mirror_items(snap)
    current_keys = set()
    for it in current:
        current_keys.add(it.key)
        result.items_seen += 1
        prev = prev_items.get(it.key)
        alive_before = prev is not None and prev.deleted_at is None
        repo.upsert_item(conn, it)
        if not alive_before or prev.raw_name != it.raw_name or prev.service_id != it.service_id:
            cats = _categories(it, ids, proc_map)
            repo.replace_item_categories(conn, it.key, cats)
            if not alive_before:
                result.events.append(ItemAdded(it.item_type, it.item_id, it.acc_invoice_id, frozenset(cats)))
        pay = payments.get(it.key)
        is_paid = 1 if pay is not None and pay.is_paid else 0
        was_paid = prev.is_paid if alive_before else 0
        repo.set_item_payment(conn, it.key, is_paid, pay.payment_type if pay else None, now)
        if is_paid and not was_paid:
            result.events.append(ItemPaid(it.item_type, it.item_id, it.acc_invoice_id))
        elif was_paid and not is_paid:
            result.events.append(PaymentRemoved(it.item_type, it.item_id, it.acc_invoice_id))

    for key, prev in prev_items.items():
        if key not in current_keys and prev.deleted_at is None:
            repo.mark_item_deleted(conn, key, now)
            result.events.append(ItemDeleted(key[0], key[1], prev.acc_invoice_id))

    # Patients
    for p in snap.patients:
        ok = identity_ok(p.name, p.family_name, p.national_id, p.phone_number)
        if repo.upsert_patient(conn, p, ok, now):
            result.events.append(PatientChanged(p.id, ok))

    if snap.shift_staff:
        repo.upsert_shift_staff(conn, snap.shift_staff)
    return result
