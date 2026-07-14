"""Manager-only payroll preview endpoint."""
from datetime import date
import logging
from typing import Optional

from django.db import DatabaseError
from ninja import Router

from accounting_ops.payroll_schemas import PayrollReportDTO
from accounting_ops.payroll_service import calculate_payroll_report
from accounting_ops.service import AccountingCommandError
from config.api_base import _jwt_auth
from config.errors import ErrorSchema, error_response

logger = logging.getLogger(__name__)
router = Router()


@router.get(
    "/accounting/reports/payroll",
    response={200: PayrollReportDTO, 403: ErrorSchema, 422: ErrorSchema, 503: ErrorSchema},
    auth=_jwt_auth,
    tags=["accounting-reports"],
)
def accounting_payroll_report(
    request,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    staff_id: Optional[int] = None,
    staff_type: Optional[str] = None,
    shift: Optional[str] = None,
):
    if getattr(request.auth, "role", "staff") not in {"admin", "manager"}:
        return 403, error_response(
            "محاسبه حقوق فقط برای مدیر یا ادمین مجاز است.", "forbidden"
        )
    try:
        return calculate_payroll_report(
            tenant_id=request.tenant_id,
            date_from=date_from,
            date_to=date_to,
            staff_id=staff_id,
            staff_type=staff_type,
            shift=shift,
        )
    except AccountingCommandError as exc:
        return exc.status, error_response(str(exc), exc.code)
    except DatabaseError as exc:
        logger.error(
            "payroll report unavailable tenant_id=%s error_type=%s",
            request.tenant_id,
            type(exc).__name__,
            exc_info=True,
        )
        return 503, error_response(
            "پایگاه دادهٔ محاسبه حقوق در دسترس نیست.",
            "accounting_report_unavailable",
        )
