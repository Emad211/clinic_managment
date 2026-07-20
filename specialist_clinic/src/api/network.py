"""Manager-only local-network status and setup guide."""
from flask import Blueprint, render_template

from src.api.auth import manager_required
from src.adapters import accounting_bridge
from src.common.network import get_network_info
from src.config.settings import Config


bp = Blueprint("network", __name__, url_prefix="/manager/network")


@bp.route("/")
@manager_required
def index():
    specialist = get_network_info(Config.PORT)
    # Accounting and Specialist are intended to run on the same server computer.
    # Browser clients use different ports; only Specialist reads clinic_new.db.
    accounting_urls = [f"http://{ip}:8080" for ip in specialist["local_ips"]]
    preferred_accounting_url = next(
        (url for ip, url in zip(specialist["local_ips"], accounting_urls) if ip != "127.0.0.1"),
        accounting_urls[0] if accounting_urls else None,
    )
    accounting = {
        "available": accounting_bridge.is_available(),
        "database_path": Config.ACCOUNTING_DB_PATH,
        "port": 8080,
        "access_urls": accounting_urls,
        "preferred_url": preferred_accounting_url,
    }
    return render_template(
        "manager/network.html",
        active_page="manager",
        specialist=specialist,
        accounting=accounting,
    )
