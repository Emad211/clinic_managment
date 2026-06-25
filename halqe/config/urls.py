"""URL configuration for halqe platform."""
from django.urls import path
from config.api import api
from platform_core.health import healthz, readyz

urlpatterns = [
    # ── Observability probes (no auth, no DB for /healthz) ───────────────────
    # These MUST be at the root (not under api/v1/) so load-balancers can
    # reach them without any path prefix.
    path("healthz", healthz),
    path("readyz", readyz),
    # ── API v1 ────────────────────────────────────────────────────────────────
    path("api/v1/", api.urls),
]
