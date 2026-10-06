"""M2 identity orchestration. Only panel repositories; no accounting IO."""
from __future__ import annotations

import hashlib
import json

from ..adapters.sqlite import account_repo, core, identity_repo as repo
from ..common.persian_text import normalize
from ..domain.identity import (clean_mobile, clean_national_id, identity_ok, identity_problems,
                               is_valid_mobile, is_valid_national_id, mask_national_id)

FIELDS = ('first_name', 'last_name', 'national_id', 'mobile')
REMINDER = 'این اطلاعات فقط در پنل ذخیره می‌شود. در مراجعهٔ بعدی، بیمار را در حسابداری با همین کد ملی ثبت کنید.'


class IdentityError(ValueError):
    def __init__(self, message, status=400, **details):
        super().__init__(message)
        self.status = status
        self.details = details


def stamp(value):
    return value.strftime('%Y-%m-%d %H:%M:%S')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def public_person(row):
    return {'id': row['id'], **{key: row[key] for key in FIELDS}}


def validated(data):
    if not isinstance(data, dict) or any(not isinstance(data.get(k, ''), str) for k in FIELDS):
        raise IdentityError('اطلاعات فرم باید متن باشد')
    if any(len(data.get(k, '')) > 100 for k in FIELDS):
        raise IdentityError('فیلدها باید حداکثر ۱۰۰ نویسه باشند')
    fields = {k: normalize(data.get(k, '')) for k in FIELDS}
    fields['national_id'] = clean_national_id(fields['national_id'])
    fields['mobile'] = clean_mobile(fields['mobile'])
    problems = identity_problems(*(fields[k] for k in FIELDS))
    return fields, problems


def eligible(conn, invoice_id):
    row = repo.invoice_identity(conn, invoice_id)
    if not row or row['patient_id'] is None or row['status'] == 'missing':
        raise IdentityError('فاکتور در آینه موجود نیست؛ وضعیت همگام‌سازی را بررسی کنید', 404)
    if row['dismissal'] or repo.patient_dismissed(conn, row['patient_id']):
        raise IdentityError('این بیمار به تأیید پذیرش تبعه است و از پیگیری خارج شده', 409)
    if not (row['waiting'] or row['status'] == 'open' and row['relevant']):
        raise IdentityError('این فاکتور دیگر هشدار هویت ندارد؛ فهرست را تازه کنید', 409)
    return row


def invoice_token(conn, row):
    person = repo.linked_person(conn, row['patient_id'])
    return fingerprint({'invoice': dict(row), 'person': dict(person) if person else None})


def detail(conn, invoice_id):
    row = eligible(conn, invoice_id)
    person = repo.linked_person(conn, row['patient_id'])
    fields = (public_person(person) if person else dict(zip(FIELDS,
              (row['name'] or '', row['family_name'] or '', row['national_id'] or '', row['phone'] or ''))))
    return {'invoice_id': invoice_id, 'patient_id': row['patient_id'], 'fields': fields,
            'token': invoice_token(conn, row), 'reminder': REMINDER}


def preview(conn, data):
    fields, problems = validated(data)
    person = repo.person_by_nid(conn, fields['national_id']) if not problems else None
    match = None
    if person:
        match = {'person': public_person(person), 'token': fingerprint(dict(person)),
                 'differences': [k for k in ('first_name', 'last_name', 'mobile') if person[k] != fields[k]]}
    return {'fields': fields, 'problems': problems, 'valid': not problems, 'match': match}


def _audit(conn, at, actor, action, entity, entity_id, before=None, after=None):
    account_repo.audit(conn, at, actor, action, entity, entity_id, before, after)


def _bind(conn, patient_id, person_id, method, actor, at):
    person = repo.person_by_id(conn, person_id)
    if not person or not identity_ok(*(person[k] for k in FIELDS)):
        raise IdentityError('هویت شخص مقصد معتبر نیست؛ اتصال متوقف شد', 409)
    previous = repo.linked_person(conn, patient_id)
    if previous:
        if previous['id'] != person_id:
            raise IdentityError('این پرونده قبلاً به شخص دیگری متصل شده؛ اتصال خودکار جایگزین نمی‌شود', 409)
    else:
        repo.insert_link(conn, patient_id, person_id, method, actor, at)
        _audit(conn, at, actor, 'identity.link', 'person_acc_link', patient_id,
               after={'person_id': person_id, 'method': method})
    repo.bind_clinical_records(conn, patient_id, person_id)
    for journey in repo.waiting_journeys(conn, patient_id):
        if journey['person_id'] not in (None, person_id):
            continue  # Never reassign a clinical record to another person.
        duplicate = repo.open_journey_for_template(conn, person_id, journey['template_code'], journey['id'])
        if duplicate:
            repo.cancel_journey(conn, journey['id'], 'duplicate', at)
            action, result = 'journey.cancel', {'status': 'cancelled', 'reason': 'duplicate', 'duplicate_of': duplicate['id']}
        else:
            repo.activate_journey(conn, journey['id'], person_id)
            action, result = 'journey.identity_ready', {'status': 'active', 'person_id': person_id}
        _audit(conn, at, actor, action, 'journey', journey['id'], dict(journey), result)


def sync_patients(conn, patient_ids, at):
    """Called inside mirror transaction AFTER the accounting connection is closed."""
    for row in repo.patient_rows(conn, patient_ids):
        pid, nid = row['acc_id'], clean_national_id(row['national_id'])
        if repo.patient_dismissed(conn, pid):
            continue
        previous = repo.linked_person(conn, pid)
        if previous:
            if not is_valid_national_id(nid) or previous['national_id'] == nid:
                _bind(conn, pid, previous['id'], 'auto_nid', 'system:sync', at)
            continue  # An edited accounting NID never silently moves an existing link.
        if not is_valid_national_id(nid):
            continue
        person = repo.person_by_nid(conn, nid)
        if not person:
            raw = repo.raw_patient(conn, pid)
            fields, problems = validated(dict(zip(FIELDS, (raw['name'] or '', raw['family_name'] or '',
                                                          raw['national_id'] or '', raw['phone'] or ''))))
            if problems:
                continue
            person_id = repo.insert_person(conn, fields, 'system:sync', at)
            _audit(conn, at, 'system:sync', 'identity.create', 'person', person_id, after=fields)
        else:
            person_id = person['id']
        _bind(conn, pid, person_id, 'auto_nid', 'system:sync', at)


def save(conn, invoice_id, data, actor, now):
    at = stamp(now)
    with core.transaction(conn):
        row = eligible(conn, invoice_id)
        fields, problems = validated(data)
        if problems:
            raise IdentityError('؛ '.join(problems), problems=problems)
        if data.get('token') != invoice_token(conn, row):
            raise IdentityError('اطلاعات پرونده تغییر کرده؛ فرم را دوباره باز کنید', 409)
        current = repo.linked_person(conn, row['patient_id'])
        if current and current['national_id'] != fields['national_id']:
            raise IdentityError('کد ملی پروندهٔ متصل قابل تغییر نیست؛ از اتصال به شخص اشتباه جلوگیری شد', 409)
        existing = repo.person_by_nid(conn, fields['national_id'])
        if existing:
            expected = preview(conn, fields)['match']
            if data.get('confirm') is not True or data.get('match_token') != expected['token']:
                raise IdentityError('این کد ملی از قبل وجود دارد؛ اختلاف‌ها را بررسی و اتصال را تأیید کنید', 409, match=expected)
            choices = data.get('choices')
            if not isinstance(choices, dict) or any(choices.get(k) not in ('existing', 'entered') for k in expected['differences']):
                raise IdentityError('برای هر اختلاف انتخاب کنید کدام اطلاعات نگه داشته شود')
            for k in expected['differences']:
                if choices[k] == 'existing':
                    fields[k] = existing[k]
            person_id = existing['id']
            if any(fields[k] != existing[k] for k in FIELDS):
                repo.update_person(conn, person_id, fields, actor, at)
                _audit(conn, at, actor, 'identity.update', 'person', person_id, public_person(existing), fields)
        else:
            person_id = repo.insert_person(conn, fields, actor, at)
            _audit(conn, at, actor, 'identity.create', 'person', person_id, after=fields)
        _bind(conn, row['patient_id'], person_id, 'manual', actor, at)
        duplicates = [r['acc_id'] for r in repo.patient_rows(conn)
                      if clean_national_id(r['national_id']) == fields['national_id']]
        sync_patients(conn, duplicates, at)
        return {'person_id': person_id, 'message': 'هویت ثبت و پرونده متصل شد', 'reminder': REMINDER}


def dismiss_foreign(conn, invoice_id, data, actor, now):
    if data.get('confirm') is not True:
        raise IdentityError('خارج‌شدن بیمار تبعه از تمام پیگیری‌ها را تأیید کنید')
    at = stamp(now)
    with core.transaction(conn):
        row = eligible(conn, invoice_id)
        if data.get('token') != invoice_token(conn, row):
            raise IdentityError('اطلاعات پرونده تغییر کرده؛ دوباره بررسی کنید', 409)
        if repo.linked_person(conn, row['patient_id']):
            raise IdentityError('پرونده به هویت ایرانی متصل است؛ نمی‌توان آن را تبعه ثبت کرد', 409)
        journeys = repo.waiting_journeys(conn, row['patient_id'])
        repo.set_dismissal(conn, invoice_id, actor, at)
        _audit(conn, at, actor, 'identity.foreign', 'identity_dismissal', invoice_id, after={'reason': 'foreign'})
        for journey in journeys:
            repo.cancel_journey(conn, journey['id'], 'foreign', at)
            _audit(conn, at, actor, 'journey.cancel', 'journey', journey['id'], dict(journey), {'reason': 'foreign'})
    return {'message': 'هشدار بسته شد؛ بیمار تبعه از پیگیری خارج شد'}


def worklist(conn):
    rows = []
    for row in repo.worklist(conn):
        if repo.patient_dismissed(conn, row['patient_id']):
            continue
        rows.append({'invoice_id': row['invoice_id'], 'patient_id': row['patient_id'],
                     'name': ' '.join(x for x in (row['first_name'] or row['name'], row['last_name'] or row['family_name']) if x),
                     'national_id_masked': mask_national_id(row['panel_nid'] or row['national_id']),
                     'categories': (row['categories'] or '').split(','), 'work_date': row['work_date']})
    return rows


def suggestions(conn, invoice_id, now):
    row = eligible(conn, invoice_id)
    if repo.linked_person(conn, row['patient_id']) or is_valid_national_id(row['national_id']):
        return []
    mobile, family = clean_mobile(row['phone']), normalize(row['family_name'])
    if not is_valid_mobile(mobile) or not family:
        return []
    out = []
    with core.transaction(conn):
        for person in repo.candidates(conn, mobile):
            if normalize(person['last_name']) != family:
                continue
            candidate = repo.suggestion(conn, invoice_id, person['id'], stamp(now))
            if candidate['status'] == 'pending':
                out.append({'person_id': person['id'], 'name': person['first_name'] + ' ' + person['last_name'],
                            'national_id_masked': mask_national_id(person['national_id'])})
    return out


def decide_suggestion(conn, invoice_id, person_id, data, actor, now):
    at = stamp(now)
    with core.transaction(conn):
        row = eligible(conn, invoice_id)
        if data.get('token') != invoice_token(conn, row):
            raise IdentityError('اطلاعات پرونده تغییر کرده؛ فرم را دوباره باز کنید', 409)
        person = repo.person_by_id(conn, person_id)
        if (not person or repo.linked_person(conn, row['patient_id']) or is_valid_national_id(row['national_id'])
                or not is_valid_mobile(row['phone']) or clean_mobile(row['phone']) != person['mobile']
                or normalize(row['family_name']) != normalize(person['last_name'])):
            raise IdentityError('پیشنهاد دیگر معتبر نیست؛ فهرست را تازه کنید', 409)
        candidate = repo.suggestion(conn, invoice_id, person_id, at)
        if candidate['status'] != 'pending':
            raise IdentityError('این پیشنهاد قبلاً بررسی شده است', 409)
        if data.get('accept') is True:
            if data.get('confirm') is not True or data.get('match_token') != fingerprint(dict(person)):
                raise IdentityError('کد ملی بیمار را بررسی و اتصال پیشنهادی را تأیید کنید', 409,
                                    match={'person': public_person(person), 'token': fingerprint(dict(person))})
            _bind(conn, row['patient_id'], person_id, 'suggestion', actor, at)
            status = 'accepted'
        elif data.get('accept') is False:
            status = 'rejected'
        else:
            raise IdentityError('نتیجهٔ پیشنهاد را انتخاب کنید')
        repo.decide_suggestion(conn, invoice_id, person_id, status, actor, at)
        _audit(conn, at, actor, 'identity.suggestion.' + status, 'match_suggestion', candidate['id'])
    return {'message': 'پیشنهاد تأیید و پرونده متصل شد' if status == 'accepted' else 'پیشنهاد رد شد'}


def compliance(conn, date_from, date_to):
    return [dict(r) for r in repo.compliance(conn, date_from, date_to)]
