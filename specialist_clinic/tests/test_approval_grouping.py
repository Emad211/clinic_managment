from src.api.sms import _group_pending_by_patient


def _row(patient_id, approval_id, name):
    return {
        'id': approval_id,
        'patient_link_id': patient_id,
        'patient_name': name,
        'national_id': f'00{patient_id}',
        'phone_number': f'0912000000{patient_id}',
    }


def test_pending_approvals_are_grouped_by_patient_and_keep_queue_order():
    pending = [_row(2, 21, 'بیمار دوم'), _row(1, 11, 'بیمار اول'),
               _row(2, 22, 'بیمار دوم')]

    groups = _group_pending_by_patient(pending)

    assert [group['patient_link_id'] for group in groups] == [2, 1]
    assert [message['id'] for message in groups[0]['messages']] == [21, 22]
    assert [message['id'] for message in groups[1]['messages']] == [11]


def test_empty_approval_queue_has_no_patient_groups():
    assert _group_pending_by_patient([]) == []
