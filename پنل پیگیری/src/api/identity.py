"""Reception identity endpoints; reports are manager/director only (06 §1)."""
from functools import wraps

from flask import Blueprint, jsonify, render_template, request

from ..app_context import get_db, now
from ..common.jalali import gregorian_from_jalali, jalali_date
from ..services import identity as service
from .security import login_required, principal

bp = Blueprint('identity', __name__)


def errors(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except service.IdentityError as exc:
            return jsonify(error=str(exc), **exc.details), exc.status
    return wrapped


def payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise service.IdentityError('بدنهٔ درخواست باید یک فرم JSON باشد')
    return data


@bp.get('/api/reception/identity')
@login_required('reception')
def worklist():
    rows = service.worklist(get_db())
    for row in rows:
        row['work_date_fa'] = jalali_date(row['work_date']) if row['work_date'] else 'نامشخص'
    return jsonify(rows=rows, total=len(rows))


@bp.get('/api/reception/identity/<int:invoice_id>')
@login_required('reception')
@errors
def detail(invoice_id):
    conn = get_db()
    result = service.detail(conn, invoice_id)
    result['suggestions'] = service.suggestions(conn, invoice_id, now())
    return jsonify(result)


@bp.post('/api/reception/identity/validate')
@login_required('reception')
@errors
def validate():
    return jsonify(service.preview(get_db(), payload()))


@bp.post('/api/reception/identity/<int:invoice_id>')
@login_required('reception')
@errors
def save(invoice_id):
    return jsonify(service.save(get_db(), invoice_id, payload(), principal().actor, now()))


@bp.post('/api/reception/identity/<int:invoice_id>/foreign')
@login_required('reception')
@errors
def foreign(invoice_id):
    return jsonify(service.dismiss_foreign(get_db(), invoice_id, payload(), principal().actor, now()))


@bp.post('/api/reception/identity/<int:invoice_id>/suggestions/<int:person_id>')
@login_required('reception')
@errors
def suggestion(invoice_id, person_id):
    return jsonify(service.decide_suggestion(get_db(), invoice_id, person_id, payload(), principal().actor, now()))


@bp.get('/reports/identity')
@login_required('manager', 'director')
def report_page():
    today = jalali_date(now().date().isoformat())
    return render_template('identity_report.html', today=today)


@bp.get('/api/reports/identity')
@login_required('manager', 'director')
@errors
def report():
    try:
        start = gregorian_from_jalali(request.args.get('from', ''))
        end = gregorian_from_jalali(request.args.get('to', ''))
        if start > end:
            raise ValueError('تاریخ شروع باید پیش از پایان باشد')
    except ValueError as exc:
        raise service.IdentityError(str(exc)) from exc
    return jsonify(rows=service.compliance(get_db(), start, end))
