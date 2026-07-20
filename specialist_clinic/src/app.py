import os
import sys
import threading
import webbrowser

from flask import Flask, redirect, url_for, session, g

from src.config.settings import Config
from src.adapters.sqlite.core import close_connection, get_db


def create_app(test_config=None):
    """Flask application factory (works in source and PyInstaller frozen modes)."""
    if getattr(sys, "frozen", False):
        base_dir = sys._MEIPASS
        template_folder = os.path.join(base_dir, "src", "templates")
        static_folder = os.path.join(base_dir, "src", "static")
    else:
        base_dir = os.path.abspath(os.path.dirname(__file__))
        template_folder = os.path.join(base_dir, "templates")
        static_folder = os.path.join(base_dir, "static")

    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)

    if test_config is None:
        app.config.from_object(Config)
    else:
        app.config.from_mapping(test_config)

    # ---- Security hardening (active only when PRODUCTION=1; local/.exe/LAN/test unchanged) ----
    from datetime import timedelta
    from src.config.settings import DEFAULT_SECRET_KEY
    if app.config.get("PRODUCTION") and not app.config.get("TESTING", False):
        if app.config.get("SECRET_KEY") in (None, DEFAULT_SECRET_KEY):
            raise RuntimeError(
                "PRODUCTION=1 but SECRET_KEY is unset or the insecure default. "
                "Set a strong SECRET_KEY environment variable before starting in production.")
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = bool(app.config.get("PRODUCTION"))
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

    # In source/dev mode pick up template edits without a restart (no effect in the
    # frozen .exe, where bundled templates never change).
    if not getattr(sys, "frozen", False):
        app.config["TEMPLATES_AUTO_RELOAD"] = True
        app.jinja_env.auto_reload = True

    app.teardown_appcontext(close_connection)

    # ---- Logging (rotating file beside the DB for the frozen .exe + console in dev) ----
    if not app.config.get("TESTING", False):
        try:
            from src.common.logging_setup import setup_app_logging
            _db = app.config.get("DATABASE_PATH") or ""
            _log_dir = (os.path.dirname(os.path.abspath(_db))
                        if _db and _db != ":memory:" else app.config.get("PROJECT_ROOT", base_dir))
            setup_app_logging(_log_dir)
        except Exception as e:
            print(f"[logging] not configured: {e}")

    # ---- Load logged-in user ----
    @app.before_request
    def load_logged_in_user():
        user_id = session.get("user_id")
        if user_id is None:
            g.user = None
        else:
            db = get_db()
            g.user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    # ---- Blueprints ----
    from src.api.auth import bp as auth_bp
    from src.api.dashboard import bp as dashboard_bp
    from src.api.patients import bp as patients_bp
    from src.api.vitals import bp as vitals_bp
    from src.api.appointments import bp as appointments_bp
    from src.api.followups import bp as followups_bp
    from src.api.sms import bp as sms_bp
    from src.api.manager import bp as manager_bp
    from src.api.control_room import bp as control_room_bp
    from src.api.ext import bp as ext_bp
    from src.api.doctor_queue import bp as doctor_queue_bp
    from src.api.patient_card import bp as patient_card_bp
    from src.api.network import bp as network_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(vitals_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(followups_bp)
    app.register_blueprint(sms_bp)
    app.register_blueprint(manager_bp)
    app.register_blueprint(control_room_bp)
    app.register_blueprint(ext_bp)
    app.register_blueprint(doctor_queue_bp)
    app.register_blueprint(patient_card_bp)
    app.register_blueprint(network_bp)

    # ---- Jinja filters ----
    @app.template_filter("jalali")
    def jalali_filter(value):
        from src.common.utils import format_jalali_datetime
        return format_jalali_datetime(value)

    @app.template_filter("jalali_date")
    def jalali_date_filter(value):
        from src.common.utils import format_jalali_date
        return format_jalali_date(value)

    @app.template_filter("fa_num")
    def fa_number_filter(value):
        if value is None:
            return ''
        try:
            num = float(value)
        except Exception:
            trans = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
            return str(value).translate(trans)
        s = f"{int(num):,}" if float(num).is_integer() else f"{num:,.1f}"
        return s.translate(str.maketrans('0123456789,', '۰۱۲۳۴۵۶۷۸۹،'))

    @app.route("/")
    def index():
        if g.user is None:
            return redirect(url_for("auth.login"))
        return redirect(url_for("dashboard.index"))

    # ---- Background scheduler (reminders + campaigns) ----
    if not app.config.get("TESTING", False):
        try:
            from src.services.scheduler import init_scheduler
            init_scheduler(app)
        except Exception as e:
            print(f"[scheduler] not started: {e}")

    return app


def open_browser():
    url = f"http://127.0.0.1:{Config.PORT}/"
    try:
        webbrowser.open(url)
    except Exception:
        pass


if __name__ == "__main__":
    application = create_app()
    threading.Timer(1.5, open_browser).start()
    application.run(debug=False,
                    host=("127.0.0.1" if application.config.get("PRODUCTION") else "0.0.0.0"),
                    port=Config.PORT, use_reloader=False, threaded=True)
