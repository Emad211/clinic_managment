from datetime import date
from ninja import Schema


class PayrollDetailDTO(Schema):
    code: str
    label: str
    count: int
    unit_price: float
    total: float


class PayrollShiftCountDTO(Schema):
    morning: int
    evening: int
    night: int


class PayrollRowDTO(Schema):
    id: int
    name: str
    staff_type: str
    type_label: str
    shift_counts: PayrollShiftCountDTO
    details: list[PayrollDetailDTO]
    gross_salary: float
    tax_amount: float
    net_salary: float


class PayrollSummaryDTO(Schema):
    staff_count: int
    gross_salary: float
    tax_amount: float
    net_salary: float


class PayrollReportDTO(Schema):
    date_from: date
    date_to: date
    summary: PayrollSummaryDTO
    rows: list[PayrollRowDTO]
