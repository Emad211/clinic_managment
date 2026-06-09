"""django-ninja API root (docs/TECH_STACK.md). Module routers are mounted here
as they come online."""

from ninja import NinjaAPI

from apps.chronic.api import router as chronic_router
from apps.patients.api import router as patients_router

api = NinjaAPI(title="Clinic Platform API", version="0.1.0")


@api.get("/health", tags=["meta"])
def health(request):
    return {"status": "ok", "service": "clinic-platform", "version": "0.1.0"}


api.add_router("/patients", patients_router)
api.add_router("/chronic", chronic_router)
