import json
import os
import sys
import threading
import webbrowser
from datetime import datetime, timedelta

import click
from flask import (
    Flask,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from src.adapters.sqlite.core import close_connection, get_db
from src.common.install_secret import (
    is_strong_secret,
    load_or_create_install_secret,
)
from src.config.settings import Config, DEFAULT_SECRET_KEY
from src.security.csrf import install_csrf
from src.security.permissions import permissions_for_template


def create_app(test_config=None):
    """Flask application factory for source and PyInstaller runtimes."""
    if getattr(sys, "frozen", False):
        base_dir = sys._MEIPASS
        template_folder = os.path.join(base_dir, "src", "templates")
        static_folder = os.path.join(base_dir, "src", "static")
    else:
        base_dir = os.path.abspath(os.path.dirname(__file__))
        template_folder = os.path.join(base_dir, "templates")
        static_folder = os.path.join(base_dir, "static")

    app = Flask(
        __name__,
        template_folder=template_folder,
        static_folder=static_folder,
    )
    app.config.from_object(Config)
    if test_config is not None:
        app.config.update(test_config)
    from src.services.activity_logger import activity_audit_marker_exists

    app.extensions["activity_audit_healthy"] = not activity_audit_marker_exists(
        app.config["DATABASE_PATH"], instance_path=app.instance_path
    )

    testing = bool(app.config.get("TESTING", False))
    production = bool(app.config.get("PRODUCTION")) and not testing
    configured_secret = app.config.get("SECRET_KEY")
    if production:
        if (
            configured_secret in (None, DEFAULT_SECRET_KEY)
            or not is_strong_secret(configured_secret)
        ):
            raise RuntimeError(
                "PRODUCTION=1 but SECRET_KEY is unset or the insecure default. "
                "Set a strong SECRET_KEY before production startup."
            )
    elif not testing and configured_secret in (None, DEFAULT_SECRET_KEY):
        app.config["SECRET_KEY"] = load_or_create_install_secret(
            database_path=app.config.get("DATABASE_PATH") or "",
            project_root=app.config.get("PROJECT_ROOT") or base_dir,
            explicit_path=app.config.get("INSTALL_SECRET_PATH"),
        )
    elif testing and not configured_secret:
        app.config["SECRET_KEY"] = "specialist-clinic-test-secret"
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = bool(
        app.config.get("PRODUCTION")
    )
    app.config.setdefault("SESSION_COOKIE_NAME", "clinic_session")
    app.config.setdefault("SESSION_REFRESH_EACH_REQUEST", False)
    app.config.setdefault("MAX_CONTENT_LENGTH", 16 * 1024 * 1024)
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
    install_csrf(app)

    if not getattr(sys, "frozen", False):
        app.config["TEMPLATES_AUTO_RELOAD"] = True
        app.jinja_env.auto_reload = True

    app.teardown_appcontext(close_connection)

    if not app.config.get("TESTING", False):
        try:
            from src.common.logging_setup import setup_app_logging

            database_path = app.config.get("DATABASE_PATH") or ""
            log_dir = (
                os.path.dirname(os.path.abspath(database_path))
                if database_path and database_path != ":memory:"
                else app.config.get("PROJECT_ROOT", base_dir)
            )
            setup_app_logging(log_dir)
        except Exception as exc:
            print(f"[logging] not configured: {exc}")

    # Safety-critical schema is installed before serving file-backed databases.
    # The core migration pass owns any copied pre-cutover database cleanup.
    if (app.config.get("DATABASE_PATH") or "") != ":memory:":
        with app.app_context():
            from src.adapters.sqlite.clinical_engine_runtime_schema import (
                ensure_runtime_schema,
            )
            ensure_runtime_schema(get_db())
    else:

        @app.before_request
        def ensure_in_memory_clinical_runtime_guards():
            from src.adapters.sqlite.clinical_engine_runtime_schema import (
                ensure_runtime_schema,
            )
            ensure_runtime_schema(get_db())

    @app.before_request
    def load_logged_in_user():
        user_id = session.get("user_id")
        if user_id is None:
            g.user = None
        else:
            g.user = get_db().execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()

    @app.context_processor
    def inject_security_context():
        return {
            "permissions": permissions_for_template(),
        }

    from src.api.appointments import bp as appointments_bp
    from src.api.auth import bp as auth_bp
    from src.api.clinical_reconciliation import (
        bp as clinical_reconciliation_bp,
    )
    from src.api.clinical_alerts import bp as clinical_alerts_bp
    from src.api.control_room import bp as control_room_bp
    from src.api.dashboard import bp as dashboard_bp
    from src.api.doctor_queue import bp as doctor_queue_bp
    from src.api.ext import bp as ext_bp
    from src.api.followups import bp as followups_bp
    from src.api.unified_followups import bp as unified_followups_bp
    from src.api.finance_review import bp as finance_review_bp
    from src.api.health import bp as health_bp
    from src.api.hypoglycemia_shadow_monitor import (
        bp as hypoglycemia_shadow_monitor_bp,
    )
    from src.api.manager import bp as manager_bp
    from src.api.patient_card import bp as patient_card_bp
    from src.api.patients import bp as patients_bp
    from src.api.sms import bp as sms_bp
    from src.api.vitals import bp as vitals_bp

    for blueprint in (
        auth_bp,
        dashboard_bp,
        patients_bp,
        clinical_reconciliation_bp,
        clinical_alerts_bp,
        vitals_bp,
        appointments_bp,
        followups_bp,
        unified_followups_bp,
        finance_review_bp,
        sms_bp,
        manager_bp,
        hypoglycemia_shadow_monitor_bp,
        control_room_bp,
        ext_bp,
        doctor_queue_bp,
        patient_card_bp,
        health_bp,
    ):
        app.register_blueprint(blueprint)

    @app.before_request
    def enforce_secure_first_run():
        from src.services.first_run_service import FirstRunService

        if not FirstRunService().setup_required():
            return None
        if request.endpoint in {
            "auth.setup",
            "health.live",
            "health.ready",
            "static",
        }:
            return None
        if (
            request.is_json
            or request.path.startswith("/api/")
            or request.accept_mimetypes.best == "application/json"
        ):
            return (
                jsonify(
                    {
                        "error": "first_run_setup_required",
                        "status": "not_ready",
                    }
                ),
                503,
            )
        return redirect(url_for("auth.setup"))

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
            return ""
        try:
            number = float(value)
        except Exception:
            return str(value).translate(
                str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
            )
        rendered = (
            f"{int(number):,}"
            if float(number).is_integer()
            else f"{number:,.1f}"
        )
        return rendered.translate(
            str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹،")
        )

    @app.route("/")
    def index():
        if g.user is None:
            return redirect(url_for("auth.login"))
        return redirect(url_for("dashboard.index"))

    # The legacy clinical-decision importer was intentionally removed. The
    # application has seed-only data and all visible decisions must originate from
    # an exact current v2 run rather than reconstructed v1 state.
    @app.cli.group("clinical-v2")
    def clinical_v2():
        """Auditable comparison and guarded Clinical Engine v2 rollout."""

    @clinical_v2.command("compare")
    @click.option(
        "--as-of",
        "as_of_text",
        required=True,
        help="Fixed Tehran-local ISO timestamp, e.g. 2026-07-22T12:00:00",
    )
    @click.option("--actor", required=True)
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["text", "json"]),
        default="text",
        show_default=True,
    )
    def clinical_v2_compare(as_of_text, actor, output_format):
        from src.services.clinical_engine.activation import (
            ClinicalEngineActivationService,
        )

        try:
            as_of = datetime.fromisoformat(as_of_text)
        except ValueError as exc:
            raise click.ClickException(
                "--as-of must be a valid ISO timestamp"
            ) from exc
        report = ClinicalEngineActivationService().build_report(
            as_of_at=as_of,
            created_by=actor,
        )
        if output_format == "json":
            click.echo(
                json.dumps(report, ensure_ascii=False, indent=2)
            )
        else:
            click.echo(
                ClinicalEngineActivationService.render_text(report)
            )

    @clinical_v2.command("status")
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["text", "json"]),
        default="text",
        show_default=True,
    )
    def clinical_v2_status(output_format):
        from src.adapters.sqlite.clinical_engine_activation_repo import (
            ClinicalEngineActivationRepository,
        )
        from src.adapters.sqlite.clinical_engine_fact_repo import (
            ClinicalEngineFactRepository,
        )

        state = ClinicalEngineActivationRepository()
        value = {
            "effective_mode": ClinicalEngineFactRepository().get_mode(),
            "raw_mode": state.raw_mode(),
            "report": state.get_json("last_report"),
            "clinical_approval": state.get_json("mapproval_clinical"),
            "technical_approval": state.get_json("mapproval_technical"),
            "seal": state.get_json("seal"),
            "rollback": state.get_json("last_rollback"),
        }
        if output_format == "json":
            click.echo(json.dumps(value, ensure_ascii=False, indent=2))
            return
        click.echo(f"effective_mode: {value['effective_mode']}")
        click.echo(f"raw_mode: {value['raw_mode']}")
        click.echo(
            f"report: {(value['report'] or {}).get('status', 'NONE')}"
        )
        click.echo(
            "clinical_approval: "
            + ("YES" if value["clinical_approval"] else "NO")
        )
        click.echo(
            "technical_approval: "
            + ("YES" if value["technical_approval"] else "NO")
        )
        click.echo(f"seal: {'VALID' if value['seal'] else 'NONE'}")

    @clinical_v2.command("approve")
    @click.option(
        "--role",
        required=True,
        type=click.Choice(["clinical", "technical"]),
    )
    @click.option("--reviewer", required=True)
    @click.option("--report-hash", required=True)
    @click.option("--note", required=True)
    def clinical_v2_approve(role, reviewer, report_hash, note):
        from src.services.clinical_engine.activation import (
            ClinicalEngineActivationService,
        )

        ClinicalEngineActivationService().approve(
            role,
            reviewer=reviewer,
            report_hash=report_hash,
            note=note,
        )
        click.echo(
            f"{role} approval recorded for report {report_hash}."
        )

    @clinical_v2.command("activate")
    @click.option(
        "--mode",
        required=True,
        type=click.Choice(["on_selected", "on"]),
    )
    @click.option("--actor", required=True)
    def clinical_v2_activate(mode, actor):
        from src.services.clinical_engine.activation import (
            ClinicalEngineActivationService,
        )

        seal = ClinicalEngineActivationService().activate(
            mode,
            activated_by=actor,
        )
        click.echo(json.dumps(seal, ensure_ascii=False, indent=2))

    @clinical_v2.command("verify-selected")
    @click.option("--reviewer", required=True)
    @click.option("--note", required=True)
    def clinical_v2_verify_selected(reviewer, note):
        from src.services.clinical_engine.activation import (
            ClinicalEngineActivationService,
        )

        ClinicalEngineActivationService().verify_selected_rollout(
            reviewer=reviewer,
            note=note,
        )
        click.echo("Selected rollout verification recorded.")

    @clinical_v2.command("promote-ruleset")
    @click.option("--actor", required=True)
    def clinical_v2_promote_ruleset(actor):
        from src.services.clinical_engine.activation import (
            ClinicalEngineActivationService,
        )

        ClinicalEngineActivationService().promote_compared_ruleset(
            promoted_by=actor
        )
        click.echo(
            "The compared SILENT ruleset was promoted to ACTIVE."
        )

    @clinical_v2.command("rollback")
    @click.option("--actor", required=True)
    @click.option("--reason", required=True)
    def clinical_v2_rollback(actor, reason):
        from src.services.clinical_engine.activation import (
            ClinicalEngineActivationService,
        )

        ClinicalEngineActivationService().rollback(
            rolled_back_by=actor,
            reason=reason,
        )
        click.echo(
            "Clinical Engine v2 rolled back to off; audit history was retained."
        )

    @app.errorhandler(400)
    def bad_request(_error):
        return (
            render_template(
                "errors/error.html",
                status_code=400,
                error_title="درخواست نامعتبر",
                error_message=(
                    "درخواست ایمن نبود یا دادهٔ ارسالی معتبر نبود. صفحه را تازه "
                    "کنید و دوباره تلاش کنید."
                ),
                active_page=None,
            ),
            400,
        )

    @app.errorhandler(403)
    def forbidden(_error):
        return (
            render_template(
                "errors/error.html",
                status_code=403,
                error_title="دسترسی غیرمجاز",
                error_message="مجوز لازم برای این عملیات ثبت نشده است.",
                active_page=None,
            ),
            403,
        )

    @app.errorhandler(404)
    def not_found(_error):
        return (
            render_template(
                "errors/error.html",
                status_code=404,
                error_title="صفحه پیدا نشد",
                error_message=(
                    "نشانی واردشده وجود ندارد یا جابه‌جا شده است."
                ),
                active_page=None,
            ),
            404,
        )

    from src.adapters.accounting_bridge import AccountingBridgeError

    @app.errorhandler(AccountingBridgeError)
    def accounting_bridge_error(error):
        app.logger.exception(
            "read-only accounting bridge failed",
            exc_info=(type(error), error, error.__traceback__),
        )
        message = error.user_message
        if request.path.startswith("/patients/api/"):
            return jsonify(
                {"error": {"code": error.code, "message": message}}
            ), error.status_code
        return (
            render_template(
                "errors/error.html",
                status_code=503,
                error_title="حسابداری در دسترس نیست",
                error_message=message,
                active_page=None,
            ),
            error.status_code,
        )

    @app.errorhandler(500)
    def internal_error(_error):
        return (
            render_template(
                "errors/error.html",
                status_code=500,
                error_title="خطای غیرمنتظره",
                error_message=(
                    "درخواست کامل نشد. دوباره تلاش کنید و در صورت تکرار، "
                    "مدیر سیستم را مطلع کنید."
                ),
                active_page=None,
            ),
            500,
        )

    if not testing and app.config.get("START_SCHEDULER", True):
        try:
            from src.services.scheduler import init_scheduler
            from src.services.first_run_service import FirstRunService

            with app.app_context():
                setup_complete = not FirstRunService().setup_required()
            if setup_complete:
                init_scheduler(app)
            else:
                app.logger.warning(
                    "[scheduler] suspended until secure first-run is complete"
                )
        except Exception as exc:
            print(f"[scheduler] not started: {exc}")

    return app


def open_browser(*, port: int | None = None) -> bool:
    url = f"http://127.0.0.1:{port or Config.PORT}/"
    if os.name == "nt":
        try:
            os.startfile(url)
            return True
        except (AttributeError, OSError):
            pass
    try:
        return bool(webbrowser.open(url, new=2))
    except (OSError, webbrowser.Error):
        return False


if __name__ == "__main__":
    application = create_app()
    threading.Timer(1.5, open_browser).start()
    application.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=False,
        use_reloader=False,
    )
