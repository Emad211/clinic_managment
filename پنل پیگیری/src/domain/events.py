"""Domain events emitted by the mirror differ (docs/02 §4). Consumed by the journey engine (M3+)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ItemAdded:
    item_type: str          # 'visit' | 'injection' | 'procedure'
    item_id: int
    invoice_id: int
    categories: frozenset[str]


@dataclass(frozen=True)
class ItemDeleted:
    item_type: str
    item_id: int
    invoice_id: int


@dataclass(frozen=True)
class ItemPaid:
    item_type: str
    item_id: int
    invoice_id: int


@dataclass(frozen=True)
class PaymentRemoved:
    item_type: str
    item_id: int
    invoice_id: int


@dataclass(frozen=True)
class InvoiceClosed:
    invoice_id: int
    total_amount: float | None


@dataclass(frozen=True)
class PatientChanged:
    acc_patient_id: int
    identity_ok: bool


DomainEvent = ItemAdded | ItemDeleted | ItemPaid | PaymentRemoved | InvoiceClosed | PatientChanged
