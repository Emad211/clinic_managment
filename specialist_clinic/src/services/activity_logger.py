"""Lightweight activity logger for the specialist app."""
from flask import g
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now


def log_activity(action_type: str, description: str = None,
                 patient_link_id: int = None, user_id: int = None, username: str = None):
    try:
        db = get_db()
        if user_id is None and getattr(g, 'user', None):
            user_id = g.user['id']
            username = g.user['username']
        if user_id is None:
            user_id, username = 0, 'system'
        db.execute(
            """
            INSERT INTO activity_logs (user_id, username, action_type, description, patient_link_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, username, action_type, description, patient_link_id,
             iran_now().strftime('%Y-%m-%d %H:%M:%S')),
        )
        db.commit()
    except Exception as e:
        print(f"[ActivityLogger] {e}")
