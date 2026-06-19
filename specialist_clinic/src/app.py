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

    # In source/dev mode pick up template edits without a restart (no effect in the
    # frozen .exe, where bundled templates never change).
    if not getattr(sys, "frozen", False):
        app.config["TEMPLATES_AUTO_RELOAD"] = True
        app.jinja_env.auto_reload = True

    app.teardown_appcontext(close_connection)

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
    application.run(debug=False, host="0.0.0.0", port=Config.PORT, use_reloader=False, threaded=True)
