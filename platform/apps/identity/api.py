"""Auth API router (django-ninja): session-based login for AppUser.

Flow (RLS-correct ordering):
  1. resolve Clinic by slug (clinic table is NOT RLS-protected)
  2. enter the clinic's tenant context (sets app.current_clinic)
  3. authenticate against app_user (which IS RLS-protected) inside that context
  4. store clinic_id + user_id in the session; TenantMiddleware reads clinic_id
     on every subsequent request.

NOTE: CSRF protection for these cookie-session POSTs is a hardening follow-up
(the scaffold relies on same-origin + a future SPA token). Do not ship to
production without it.
"""

from ninja import Router, Schema, Status

from apps.common.tenant import tenant_context
from apps.identity.models import AppUser, Clinic
from apps.identity.services import AuthError, authenticate

router = Router(tags=["auth"])


class LoginIn(Schema):
    clinic_slug: str
    username: str
    password: str


class UserOut(Schema):
    id: str
    username: str
    role: str
    full_name: str = ""
    clinic_id: str
    clinic_slug: str
    is_licensed: bool = False
    can_practice_clinically: bool = False


def _user_payload(user: AppUser, clinic: Clinic) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "role": user.role,
        "full_name": user.full_name or "",
        "clinic_id": str(clinic.id),
        "clinic_slug": clinic.slug,
        "is_licensed": user.is_licensed,
        "can_practice_clinically": user.can_practice_clinically(),
    }


@router.post("/login", response={200: UserOut, 401: dict, 404: dict})
def login(request, data: LoginIn):
    try:
        clinic = Clinic.objects.get(slug=data.clinic_slug)
    except Clinic.DoesNotExist:
        return Status(404, {"detail": "کلینیک یافت نشد.", "code": "clinic_not_found"})

    with tenant_context(clinic.id):
        try:
            user = authenticate(clinic, data.username, data.password)
        except AuthError as e:
            return Status(401, {"detail": e.message, "code": e.code})
        payload = _user_payload(user, clinic)

    request.session["clinic_id"] = str(clinic.id)
    request.session["user_id"] = str(user.id)
    return Status(200, payload)


@router.post("/logout", response={200: dict})
def logout(request):
    request.session.flush()
    return Status(200, {"detail": "خروج انجام شد."})


@router.get("/me", response={200: UserOut, 401: dict})
def me(request):
    clinic_id = request.session.get("clinic_id")
    user_id = request.session.get("user_id")
    if not clinic_id or not user_id:
        return Status(401, {"detail": "وارد نشده‌اید.", "code": "unauthenticated"})
    with tenant_context(clinic_id):
        try:
            clinic = Clinic.objects.get(id=clinic_id)
            user = AppUser.objects.get(id=user_id)
        except (Clinic.DoesNotExist, AppUser.DoesNotExist):
            request.session.flush()
            return Status(401, {"detail": "نشست نامعتبر است.", "code": "invalid_session"})
        return Status(200, _user_payload(user, clinic))
