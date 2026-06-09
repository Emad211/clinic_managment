"""django-ninja API root (docs/TECH_STACK.md). Module routers are mounted here
as they come online. For now: a health endpoint to verify the wiring."""

from ninja import NinjaAPI

api = NinjaAPI(title="Clinic Platform API", version="0.1.0")


@api.get("/health", tags=["meta"])
def health(request):
    return {"status": "ok", "service": "clinic-platform", "version": "0.1.0"}
