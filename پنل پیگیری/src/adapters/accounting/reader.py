"""Query contract with the accounting DB (docs/03 §5).

Every statement that may run against accounting is listed in :data:`QUERIES`.
Each one names its columns explicitly and must use a primary key or an existing
index; tests/test_bridge_safety.py checks every plan with EXPLAIN QUERY PLAN,
and the startup schema check repeats that on the real file. Adding a query
means adding it here *and* to the table in docs/03 §5.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .bridge import ReadSession

NEW_INVOICES_LIMIT = 500
NEW_LOGS_LIMIT = 1000

QUERIES: dict[str, str] = {
    "Q1": "SELECT id, patient_id, status, work_date, shift, opened_at, closed_at, opened_by, total_amount "
          "FROM invoices WHERE id > ? ORDER BY id LIMIT ?",
    "Q2": "SELECT id, patient_id, status, work_date, shift, opened_at, closed_at, opened_by, total_amount "
          "FROM invoices WHERE id IN ({ids})",
    "Q3": "SELECT id, invoice_id, patient_id, doctor_id, work_date, shift, visit_date, price "
          "FROM visits WHERE invoice_id IN ({ids})",
    "Q4": "SELECT id, invoice_id, patient_id, service_id, injection_type, nurse_id, doctor_id, total_price, work_date "
          "FROM injections WHERE invoice_id IN ({ids})",
    "Q5": "SELECT id, invoice_id, patient_id, procedure_type, performer_type, doctor_id, nurse_id, price, work_date "
          "FROM procedures WHERE invoice_id IN ({ids})",
    "Q6": "SELECT invoice_id, item_type, item_id, payment_type, is_paid, updated_at "
          "FROM invoice_item_payments WHERE invoice_id IN ({ids})",
    "Q7": "SELECT id, name, family_name, national_id, phone_number, is_foreign "
          "FROM patients WHERE id IN ({ids})",
    "Q8": "SELECT a.user_id, a.active_shift, a.work_date, a.shift_started_at "
          "FROM user_active_shift AS a JOIN users AS u ON u.id = a.user_id "
          "WHERE u.role = 'reception' ORDER BY a.shift_started_at DESC LIMIT 1",
    "Q9": "SELECT work_date, shift, doctor_id, nurse_id FROM shift_staff WHERE work_date >= ?",
    "Q10": "SELECT id, action_type, invoice_id, target_type, target_id "
           "FROM activity_logs WHERE id > ? ORDER BY id LIMIT ?",
    "Q11": "SELECT id, full_name, staff_type, is_active FROM medical_staff",
    "Q12": "SELECT id, service_name, is_active FROM nursing_services",
    "Q13": "SELECT id, username, password_hash, role, full_name, is_active, locked_until "
           "FROM users WHERE username = ?",
    "Q14": "SELECT id, name, family_name, national_id, phone_number, is_foreign "
           "FROM patients WHERE national_id = ?",
    "Q15": "SELECT max(id) FROM invoices WHERE work_date < ?",
    "Q16": "SELECT max(id) FROM activity_logs",
}
# Q2 reads the same columns as Q1 (docs/03 lists a subset): a watched invoice
# may have been created before the panel first saw it.
# Q16 is the first-run activity_logs watermark (docs/03 §4 "first run").

# Tables that may be scanned because they are tiny (docs/03 §5). Aliases count.
SMALL_TABLES = frozenset({"medical_staff", "nursing_services", "user_active_shift", "users", "a", "u"})


# ---------------------------------------------------------------- row types
@dataclass(frozen=True, slots=True)
class AccInvoice:
    id: int
    patient_id: int
    status: str
    work_date: str | None
    shift: str | None
    opened_at: str | None
    closed_at: str | None
    opened_by: str | None
    total_amount: float | None


@dataclass(frozen=True, slots=True)
class AccVisit:
    id: int
    invoice_id: int
    patient_id: int
    doctor_id: int | None
    work_date: str | None
    shift: str | None
    visit_date: str | None
    price: float | None


@dataclass(frozen=True, slots=True)
class AccInjection:
    id: int
    invoice_id: int
    patient_id: int
    service_id: int | None
    injection_type: str
    nurse_id: int | None
    doctor_id: int | None
    total_price: float | None
    work_date: str | None


@dataclass(frozen=True, slots=True)
class AccProcedure:
    id: int
    invoice_id: int
    patient_id: int
    procedure_type: str
    performer_type: str | None
    doctor_id: int | None
    nurse_id: int | None
    price: float | None
    work_date: str | None


@dataclass(frozen=True, slots=True)
class AccPayment:
    invoice_id: int
    item_type: str
    item_id: int
    payment_type: str | None
    is_paid: int | None
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class AccPatient:
    id: int
    name: str
    family_name: str
    national_id: str | None
    phone_number: str | None
    is_foreign: int | None


@dataclass(frozen=True, slots=True)
class AccActiveShift:
    user_id: int
    active_shift: str
    work_date: str
    shift_started_at: str | None


@dataclass(frozen=True, slots=True)
class AccShiftStaff:
    work_date: str
    shift: str
    doctor_id: int | None
    nurse_id: int | None


@dataclass(frozen=True, slots=True)
class AccLog:
    id: int
    action_type: str
    invoice_id: int | None
    target_type: str | None
    target_id: int | None


@dataclass(frozen=True, slots=True)
class AccStaff:
    id: int
    full_name: str
    staff_type: str
    is_active: int | None


@dataclass(frozen=True, slots=True)
class AccNursingService:
    id: int
    service_name: str
    is_active: int | None


@dataclass(frozen=True, slots=True)
class AccUser:
    id: int
    username: str
    password_hash: bytes | str
    role: str
    full_name: str | None
    is_active: int
    locked_until: str | None


@dataclass(frozen=True)
class PollRequest:
    wm_invoice_id: int
    wm_activity_log_id: int
    watched_invoice_ids: frozenset[int]
    shift_staff_since: str               # YYYY-MM-DD (yesterday; 84 days back on first fill)


@dataclass
class PollSnapshot:
    """Everything one poll cycle read, from one consistent snapshot (docs/03 §4)."""
    new_invoices: list[AccInvoice] = field(default_factory=list)
    watched_invoices: list[AccInvoice] = field(default_factory=list)
    visits: list[AccVisit] = field(default_factory=list)
    injections: list[AccInjection] = field(default_factory=list)
    procedures: list[AccProcedure] = field(default_factory=list)
    payments: list[AccPayment] = field(default_factory=list)
    patients: list[AccPatient] = field(default_factory=list)
    active_shift: AccActiveShift | None = None
    shift_staff: list[AccShiftStaff] = field(default_factory=list)
    logs: list[AccLog] = field(default_factory=list)
    item_invoice_ids: frozenset[int] = frozenset()   # invoices whose items were fully read


# ---------------------------------------------------------------- reads
def read_poll(s: ReadSession, req: PollRequest) -> PollSnapshot:
    """Q1–Q10 in the order of docs/03 §4. Must run inside one bridge cycle."""
    snap = PollSnapshot()
    snap.new_invoices = [AccInvoice(*r) for r in s.fetch(QUERIES["Q1"], (req.wm_invoice_id, NEW_INVOICES_LIMIT))]
    if req.watched_invoice_ids:
        snap.watched_invoices = [AccInvoice(*r) for r in s.fetch_in(QUERIES["Q2"], req.watched_invoice_ids)]

    invoice_ids = frozenset(req.watched_invoice_ids) | {inv.id for inv in snap.new_invoices}
    snap.item_invoice_ids = invoice_ids
    if invoice_ids:
        snap.visits = [AccVisit(*r) for r in s.fetch_in(QUERIES["Q3"], invoice_ids)]
        snap.injections = [AccInjection(*r) for r in s.fetch_in(QUERIES["Q4"], invoice_ids)]
        snap.procedures = [AccProcedure(*r) for r in s.fetch_in(QUERIES["Q5"], invoice_ids)]
        snap.payments = [AccPayment(*r) for r in s.fetch_in(QUERIES["Q6"], invoice_ids)]
        patient_ids = {inv.patient_id for inv in (*snap.new_invoices, *snap.watched_invoices)}
        if patient_ids:
            snap.patients = [AccPatient(*r) for r in s.fetch_in(QUERIES["Q7"], patient_ids)]

    rows = s.fetch(QUERIES["Q8"])
    snap.active_shift = AccActiveShift(*rows[0]) if rows else None
    snap.shift_staff = [AccShiftStaff(*r) for r in s.fetch(QUERIES["Q9"], (req.shift_staff_since,))]
    snap.logs = [AccLog(*r) for r in s.fetch(QUERIES["Q10"], (req.wm_activity_log_id, NEW_LOGS_LIMIT))]
    return snap


def read_staff(s: ReadSession) -> tuple[list[AccStaff], list[AccNursingService]]:
    """Q11 + Q12, every 60 s."""
    return ([AccStaff(*r) for r in s.fetch(QUERIES["Q11"])],
            [AccNursingService(*r) for r in s.fetch(QUERIES["Q12"])])


def read_user(s: ReadSession, username: str) -> AccUser | None:
    """Q13, for login."""
    rows = s.fetch(QUERIES["Q13"], (username,))
    return AccUser(*rows[0]) if rows else None


def read_patient_by_national_id(s: ReadSession, national_id: str) -> AccPatient | None:
    """Q14, for identity linking."""
    rows = s.fetch(QUERIES["Q14"], (national_id,))
    return AccPatient(*rows[0]) if rows else None


def read_initial_watermarks(s: ReadSession, today: str) -> tuple[int, int]:
    """Q15 + Q16, first run only: start from today's invoices and the current log tail."""
    (wm_invoice,), = s.fetch(QUERIES["Q15"], (today,))
    (wm_log,), = s.fetch(QUERIES["Q16"])
    return int(wm_invoice or 0), int(wm_log or 0)


def sample_params(name: str) -> tuple[str, tuple]:
    """A runnable form of each query, used for plan checks (one IN parameter)."""
    sql = QUERIES[name]
    if "{ids}" in sql:
        return sql.format(ids="?"), (1,)
    return sql, {
        "Q1": (0, NEW_INVOICES_LIMIT), "Q9": ("2000-01-01",), "Q10": (0, NEW_LOGS_LIMIT),
        "Q13": ("x",), "Q14": ("0000000000",), "Q15": ("2000-01-01",),
    }.get(name, ())


def iter_query_names() -> Iterable[str]:
    return QUERIES.keys()
