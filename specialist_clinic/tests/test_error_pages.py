import os
import tempfile

from src.app import create_app


def _app(folder):
    return create_app({
        'TESTING': True,
        'PROPAGATE_EXCEPTIONS': False,
        'DATABASE_PATH': os.path.join(folder, 'errors.db'),
        'BACKUP_FOLDER': os.path.join(folder, 'backups'),
        'SECRET_KEY': 'test',
    })


def test_not_found_uses_product_error_page():
    with tempfile.TemporaryDirectory() as folder:
        response = _app(folder).test_client().get('/missing-page')
    assert response.status_code == 404
    assert 'صفحه پیدا نشد'.encode() in response.data
    assert b'error-state' in response.data


def test_internal_error_hides_stack_trace_and_offers_recovery():
    with tempfile.TemporaryDirectory() as folder:
        app = _app(folder)

        def boom():
            raise RuntimeError('private diagnostic detail')

        app.add_url_rule('/boom', view_func=boom)
        response = app.test_client().get('/boom')

    assert response.status_code == 500
    assert 'خطای غیرمنتظره'.encode() in response.data
    assert b'private diagnostic detail' not in response.data
    assert b'/auth/login' in response.data
