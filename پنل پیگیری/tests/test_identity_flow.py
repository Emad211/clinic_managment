"""M2 acceptance through authenticated API, synthetic accounting only."""
import hashlib
import sqlite3

import pytest

from accounting_factory import BP_CHECK_ID, BS_TEST_ID
from test_app import NOW, T, env, login, make_doctor, post_json
from src.adapters.sqlite import core

FIELDS = dict(first_name='مریم', last_name='حسینی', national_id='0499370899', mobile='09121234567')
BASE = '/api/reception/identity'


def invoice(env, name='خ', family='حسینی', nid=None, phone=None, foreign=0, category='visit'):
    app, rt, rec, _ = env
    pid = rec.add_patient(name, family, nid, phone, foreign)
    iid = rec.open_invoice(pid, T, 'morning')
    if category == 'visit':
        rec.add_visit(iid, 1)
    elif category:
        rec.add_injection(iid, BS_TEST_ID if category == 'bs_test' else BP_CHECK_ID, category)
    assert rt.poller.step().ok
    return pid, iid


def client(env, username='reza', password='recep-pass'):
    c = env[0].test_client()
    assert login(c, username, password).status_code == 302
    return c


def db(env):
    return core.connect(env[1].settings.panel_db_path)


def body(c, iid, **fields):
    token = c.get(f'{BASE}/{iid}').get_json()['token']
    return {**FIELDS, 'token': token, **fields}


def confirm(c, iid, data, choices=None):
    match = post_json(c, BASE + '/validate', data).get_json()['match']
    return post_json(c, f'{BASE}/{iid}', {**data, 'confirm': True, 'match_token': match['token'],
                                          'choices': choices if choices is not None else {k: 'existing' for k in match['differences']}})


def waiting(conn, iid, template='renewal'):
    jid = conn.execute("INSERT INTO journey(template_code,template_version,params,origin_kind,origin_acc_invoice_id,"
                       "start_date,status,created_at,created_by) VALUES (?,1,'{}','encounter',?,?,'awaiting_identity',?,'doctor:1')",
                       (template,iid,T,T+' 09:00:00')).lastrowid
    conn.execute("INSERT INTO journey_step(journey_id,seq,kind,due_date,purpose,status) "
                 "VALUES (?,1,'call',?,'renewal_reminder','pending')",(jid,T))
    return jid


@pytest.mark.parametrize('category', ['visit','bs_test','bp_check'])
def test_incomplete_open_invoice_alert_and_raw_prefill(env, category):
    pid, iid = invoice(env, category=category, foreign=1)
    c = client(env)
    rows = c.get(BASE).get_json()['rows']
    row = next(r for r in rows if r['invoice_id'] == iid)
    assert row['name'] == 'خ حسینی' and category in row['categories']
    assert 'national_id' not in row and 'mobile' not in row
    form = c.get(f'{BASE}/{iid}').get_json()
    assert form['fields']['first_name'] == 'خ' and form['fields']['national_id'] == ''
    assert 'فقط در پنل' in form['reminder']


def test_create_local_identity_preserves_raw_mirror_and_accounting_bytes(env):
    pid, iid = invoice(env, foreign=1)
    c = client(env)
    digest = hashlib.sha256(env[2].path.read_bytes()).hexdigest()
    response = post_json(c, f'{BASE}/{iid}', body(c,iid))
    assert response.status_code == 200
    with db(env) as conn:
        p = conn.execute('SELECT * FROM person WHERE id=?',(response.get_json()['person_id'],)).fetchone()
        assert p['first_name'] == 'مریم' and p['created_by'] == 'acc:reza'
        link = conn.execute('SELECT * FROM person_acc_link WHERE acc_patient_id=?',(pid,)).fetchone()
        assert link['method'] == 'manual'
        raw = conn.execute('SELECT * FROM acc_patient WHERE acc_id=?',(pid,)).fetchone()
        assert raw['name'] == 'خ' and raw['national_id'] is None and raw['identity_ok'] == 0
        actions = {r[0] for r in conn.execute('SELECT action FROM audit_log')}
        assert {'identity.create','identity.link'} <= actions
    assert iid not in [r['invoice_id'] for r in c.get(BASE).get_json()['rows']]
    assert env[1].poller.step().ok
    assert hashlib.sha256(env[2].path.read_bytes()).hexdigest() == digest
    with db(env) as conn:
        assert conn.execute('SELECT first_name FROM person WHERE id=?',(p['id'],)).fetchone()[0] == 'مریم'


def test_existing_nid_requires_confirmation_and_each_difference(env):
    _, first = invoice(env)
    c = client(env)
    assert post_json(c,f'{BASE}/{first}',body(c,first)).status_code == 200
    pid, second = invoice(env, family='احمدی')
    data = body(c,second,first_name='سارا',last_name='احمدی',mobile='09129876543')
    response = post_json(c,f'{BASE}/{second}',data)
    assert response.status_code == 409
    match = response.get_json()['match']
    assert set(match['differences']) == {'first_name','last_name','mobile'}
    assert confirm(c,second,data,{}).status_code == 400
    response = confirm(c,second,data,{'first_name':'existing','last_name':'existing','mobile':'entered'})
    assert response.status_code == 200
    with db(env) as conn:
        assert conn.execute('SELECT count(*) FROM person').fetchone()[0] == 1
        person = conn.execute('SELECT * FROM person').fetchone()
        assert person['first_name'] == 'مریم' and person['last_name'] == 'حسینی' and person['mobile'] == '09129876543'
        assert conn.execute('SELECT person_id FROM person_acc_link WHERE acc_patient_id=?',(pid,)).fetchone()[0] == person['id']
        assert conn.execute("SELECT count(*) FROM audit_log WHERE action='identity.update'").fetchone()[0] == 1


def test_future_and_already_mirrored_nid_duplicates_auto_link_idempotently(env):
    original, iid = invoice(env)
    duplicate, _ = invoice(env,nid='۰۴۹۹۳۷۰۸۹۹')
    c = client(env)
    assert post_json(c,f'{BASE}/{iid}',body(c,iid)).status_code == 200
    future, _ = invoice(env,nid=FIELDS['national_id'])
    with db(env) as conn:
        links = {r['acc_patient_id']:r for r in conn.execute('SELECT * FROM person_acc_link')}
        assert links[original]['method'] == 'manual'
        assert links[duplicate]['method'] == links[future]['method'] == 'auto_nid'
        assert len({links[p]['person_id'] for p in (original,duplicate,future)}) == 1
        before = conn.execute('SELECT count(*) FROM audit_log').fetchone()[0]
    assert env[1].poller.step().ok
    with db(env) as conn:
        assert conn.execute('SELECT count(*) FROM audit_log').fetchone()[0] == before


@pytest.mark.parametrize('data,expected', [
    ({'first_name':'خ'},'نام کوچک کامل وارد شود'),
    ({'last_name':'ا'},'نام خانوادگی کامل وارد شود'),
    ({'national_id':''},'کد ملی وارد نشده است'),
    ({'national_id':'1111111111'},'کد ملی نامعتبر است (رقم کنترل)'),
    ({'national_id':'0499370890'},'کد ملی نامعتبر است (رقم کنترل)'),
    ({'mobile':'08123456789'},'موبایل باید ۱۱ رقم و با ۰۹ شروع شود'),
    ({'mobile':'091234'},'موبایل باید ۱۱ رقم و با ۰۹ شروع شود'),
])
def test_validation_live_and_save_precise_errors_without_writes(env,data,expected):
    _, iid = invoice(env)
    c = client(env)
    preview = post_json(c,BASE+'/validate',{**FIELDS,**data}).get_json()
    assert preview['valid'] is False and expected in preview['problems']
    response = post_json(c,f'{BASE}/{iid}',body(c,iid,**data))
    assert response.status_code == 400 and expected in response.get_json()['error']
    with db(env) as conn:
        assert conn.execute('SELECT count(*) FROM person').fetchone()[0] == 0


def test_persian_digit_identity_saved_normalized(env):
    _, iid = invoice(env)
    c = client(env)
    response = post_json(c,f'{BASE}/{iid}',body(c,iid,national_id='۰۴۹۹۳۷۰۸۹۹',mobile='۰۹۱۲۱۲۳۴۵۶۷'))
    assert response.status_code == 200
    with db(env) as conn:
        assert conn.execute('SELECT national_id,mobile FROM person').fetchone()[:] == ('0499370899','09121234567')


def test_awaiting_identity_on_closed_invoice_activates_and_duplicate_cancels(env):
    """G9: of two waiting journeys of one template, the newer one survives activation."""
    pid, iid = invoice(env)
    with db(env) as conn:
        older, newer = waiting(conn,iid), waiting(conn,iid)
    env[2]._run("UPDATE invoices SET status='closed' WHERE id=?",(iid,))
    assert env[1].poller.step().ok
    c = client(env)
    assert iid in [r['invoice_id'] for r in c.get(BASE).get_json()['rows']]
    assert post_json(c,f'{BASE}/{iid}',body(c,iid)).status_code == 200
    with db(env) as conn:
        assert conn.execute('SELECT status,person_id FROM journey WHERE id=?',(newer,)).fetchone()[:] == ('active',1)
        assert conn.execute('SELECT status,close_reason FROM journey WHERE id=?',(older,)).fetchone()[:] == ('cancelled','duplicate')
        assert conn.execute('SELECT status FROM journey_step WHERE journey_id=?',(older,)).fetchone()[0] == 'cancelled'
    assert iid not in [r['invoice_id'] for r in c.get(BASE).get_json()['rows']]


def test_foreign_requires_explicit_confirmation_cancels_waiters_and_stays_dismissed(env):
    pid, iid = invoice(env,foreign=1)
    with db(env) as conn:
        jid = waiting(conn,iid)
    c = client(env)
    data = {'token':body(c,iid)['token']}
    assert post_json(c,f'{BASE}/{iid}/foreign',data).status_code == 400
    assert post_json(c,f'{BASE}/{iid}/foreign',{**data,'confirm':True}).status_code == 200
    assert env[1].poller.step().ok
    with db(env) as conn:
        assert conn.execute('SELECT reason,by_user FROM identity_dismissal WHERE acc_invoice_id=?',(iid,)).fetchone()[:] == ('foreign','acc:reza')
        assert conn.execute('SELECT status,close_reason FROM journey WHERE id=?',(jid,)).fetchone()[:] == ('cancelled','foreign')
    assert iid not in [r['invoice_id'] for r in c.get(BASE).get_json()['rows']]
    assert post_json(c,f'{BASE}/{iid}',{**FIELDS,'token':data['token']}).status_code == 409
    env[2].update_patient(pid,national_id=FIELDS['national_id'],name='مریم',phone_number=FIELDS['mobile'])
    assert env[1].poller.step().ok
    with db(env) as conn:
        assert conn.execute('SELECT count(*) FROM person_acc_link WHERE acc_patient_id=?',(pid,)).fetchone()[0] == 0


def test_phone_never_auto_links_and_suggestion_requires_review(env):
    _, iid = invoice(env)
    c = client(env)
    assert post_json(c,f'{BASE}/{iid}',body(c,iid)).status_code == 200
    phone_only, other = invoice(env,family='احمدی',phone=FIELDS['mobile'])
    pid, suggested = invoice(env,phone=FIELDS['mobile'])
    with db(env) as conn:
        assert conn.execute('SELECT count(*) FROM person_acc_link WHERE acc_patient_id IN (?,?)',(phone_only,pid)).fetchone()[0] == 0
    assert c.get(f'{BASE}/{other}').get_json()['suggestions'] == []
    form = c.get(f'{BASE}/{suggested}').get_json()
    assert len(form['suggestions']) == 1
    person_id = form['suggestions'][0]['person_id']
    url = f'{BASE}/{suggested}/suggestions/{person_id}'
    data = {'token':form['token'],'accept':True}
    response = post_json(c,url,data)
    assert response.status_code == 409
    match = response.get_json()['match']
    assert post_json(c,url,{**data,'confirm':True,'match_token':match['token']}).status_code == 200
    with db(env) as conn:
        assert conn.execute('SELECT method FROM person_acc_link WHERE acc_patient_id=?',(pid,)).fetchone()[0] == 'suggestion'


def test_suggestion_rejection_persists(env):
    _, iid = invoice(env)
    c = client(env)
    post_json(c,f'{BASE}/{iid}',body(c,iid))
    _, second = invoice(env,phone=FIELDS['mobile'])
    form = c.get(f'{BASE}/{second}').get_json()
    candidate = form['suggestions'][0]
    url = f"{BASE}/{second}/suggestions/{candidate['person_id']}"
    assert post_json(c,url,{'token':form['token'],'accept':False}).status_code == 200
    assert c.get(f'{BASE}/{second}').get_json()['suggestions'] == []


def test_stale_invoice_and_person_confirmation_prevent_lost_updates(env):
    pid, iid = invoice(env)
    c = client(env)
    data = body(c,iid)
    env[2].update_patient(pid,family_name='احمدی')
    env[1].poller.step()
    assert post_json(c,f'{BASE}/{iid}',data).status_code == 409
    assert post_json(c,f'{BASE}/{iid}',body(c,iid)).status_code == 200
    _, second = invoice(env)
    _, third = invoice(env)
    stale = body(c,second)
    match = post_json(c,BASE+'/validate',stale).get_json()['match']
    assert confirm(c,third,body(c,third,mobile='09129999999'),{'mobile':'entered'}).status_code == 200
    response = post_json(c,f'{BASE}/{second}',{**stale,'confirm':True,'match_token':match['token'],'choices':{}})
    assert response.status_code == 409 and 'match' in response.get_json()


def test_effective_identity_reaches_doctor_queue_but_poll_does_not_overwrite(env):
    make_doctor(env[0],env[1])
    pid, iid = invoice(env)
    reception = client(env)
    assert post_json(reception,f'{BASE}/{iid}',body(reception,iid)).status_code == 200
    doctor = client(env,'dr.alef','doctor-pass')
    row = next(r for r in doctor.get('/api/doctor/queue').get_json()['rows'] if r['invoice_id'] == iid)
    assert row['name'] == 'مریم حسینی' and row['identity_ok'] and row['national_id_masked'] == '…0899'
    env[2].update_patient(pid,name='خ',family_name='جدید')
    env[1].poller.step()
    row = next(r for r in doctor.get('/api/doctor/queue').get_json()['rows'] if r['invoice_id'] == iid)
    assert row['name'] == 'مریم حسینی'


def test_changed_accounting_nid_does_not_reassign_existing_link(env):
    pid, iid = invoice(env)
    c = client(env)
    first = post_json(c,f'{BASE}/{iid}',body(c,iid)).get_json()['person_id']
    env[2].update_patient(pid,national_id='0067749828')
    assert env[1].poller.step().ok
    with db(env) as conn:
        assert conn.execute('SELECT person_id FROM person_acc_link WHERE acc_patient_id=?',(pid,)).fetchone()[0] == first
    assert post_json(c,f'{BASE}/{iid}',body(c,iid,national_id='0067749828')).status_code == 409


def test_report_separates_accounting_panel_and_foreign_by_user_and_shift(env):
    _, iid = invoice(env)
    _, foreign = invoice(env,foreign=1)
    c = client(env)
    post_json(c,f'{BASE}/{iid}',body(c,iid))
    post_json(c,f'{BASE}/{foreign}/foreign',{'token':body(c,foreign)['token'],'confirm':True})
    manager = client(env,'boss','boss-pass')
    response = manager.get('/api/reports/identity?from=۱۴۰۵/۰۷/۱۴&to=۱۴۰۵/۰۷/۱۴')
    assert response.status_code == 200
    row = next(r for r in response.get_json()['rows'] if r['username'] == 'recep1' and r['shift'] == 'morning')
    assert row['total'] >= 2 and row['panel_linked'] >= 1 and row['foreign_excluded'] == 1
    assert row['effective_complete'] == row['panel_linked']
    assert manager.get('/reports/identity').status_code == 200
    assert manager.get('/api/reports/identity?from=invalid&to=invalid').status_code == 400
    assert manager.get('/api/reports/identity?from=۱۴۰۵/۰۷/۱۵&to=۱۴۰۵/۰۷/۱۴').status_code == 400


def test_roles_csrf_and_bad_payloads(env):
    _, iid = invoice(env)
    anonymous = env[0].test_client()
    assert anonymous.get(BASE).status_code == 401
    manager = client(env,'boss','boss-pass')
    assert manager.get(BASE).status_code == 403
    assert post_json(manager,f'{BASE}/{iid}',FIELDS).status_code == 403
    reception = client(env)
    assert reception.get('/api/reports/identity').status_code == 403
    assert reception.post(f'{BASE}/{iid}',json=FIELDS).status_code == 400
    for payload in ([],None,'text',{'first_name':[]},{'national_id':123},{'mobile':None}):
        assert post_json(reception,BASE+'/validate',payload).status_code == 400
    assert reception.get(f'{BASE}/999999').status_code == 404
    make_doctor(env[0],env[1],director=True)
    director = client(env,'dr.alef','doctor-pass')
    assert director.get('/reports/identity').status_code == 200
    assert director.get(BASE).status_code == 403


def test_m1_to_m2_upgrade_baselines_mirror_and_backs_up_before_ddl(tmp_path):
    dbpath, backups = tmp_path/'m1.db', tmp_path/'backups'
    core.init_db(dbpath,backups)
    with core.connect(dbpath) as conn:
        conn.execute('DROP TABLE identity_observation')
        conn.execute("UPDATE schema_meta SET value='2' WHERE key='version'")
        conn.execute("INSERT INTO acc_patient(acc_id,name,family_name,identity_ok,last_seen_at) VALUES (1,'خ','حسینی',0,'t')")
        conn.execute("INSERT INTO acc_invoice(acc_id,acc_patient_id,status,first_seen_at,last_seen_at) VALUES (1,1,'open','t','t')")
        conn.execute("INSERT INTO acc_item(item_type,item_id,acc_invoice_id) VALUES ('visit',1,1)")
        conn.execute("INSERT INTO acc_item_category VALUES ('visit',1,'visit')")
    assert core.init_db(dbpath,backups) == core.SCHEMA_VERSION
    with core.connect(dbpath) as conn:
        assert conn.execute('SELECT acc_invoice_id,accounting_identity_ok FROM identity_observation').fetchone()[:] == (1,0)
        assert conn.execute('SELECT name FROM acc_patient').fetchone()[0] == 'خ'
    copies = list(backups.glob('peygiri_panel_pre-migration-v2_*.db'))
    assert len(copies) == 1
    with sqlite3.connect(copies[0]) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='identity_observation'").fetchone() is None
        assert conn.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()[0] == '2'
    core.init_db(dbpath,backups)
    assert len(list(backups.glob('*.db'))) == 1
