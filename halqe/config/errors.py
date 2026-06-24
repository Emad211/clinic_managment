"""
Shared error contract for the Halqe Platform API.

Every error response body has exactly two fields:
  detail  — human-readable message (Persian where user-facing).
            The Next.js client reads this field (`body?.detail` in api.ts).
  code    — stable machine-readable snake_case identifier for the error.

Usage:
    from config.errors import ErrorSchema, error_response

    # In a response= map:
    response={200: SomeDTO, 404: ErrorSchema, 409: ErrorSchema}

    # In the handler body:
    return 404, error_response("پیدا نشد.", "not_found")

Machine codes (stable, add but never rename):
    invalid_credentials  — wrong username/password or inactive account
    account_locked       — account temporarily locked after failed attempts
    not_found            — requested resource does not exist for this tenant
    conflict             — state transition not allowed (e.g. already done)
    validation_error     — invalid request value (e.g. bad action type)
"""
from ninja import Schema


class ErrorSchema(Schema):
    """Uniform error response body — the single error shape for all endpoints."""
    detail: str   # human-readable; the Next.js client reads this field
    code: str     # stable machine-readable identifier


def error_response(detail: str, code: str) -> dict:
    """
    Build an error response dict that serialises to ErrorSchema.

    Returns a plain dict (not an ErrorSchema instance) because django-ninja
    accepts both forms for error tuples.  A dict keeps the handler one-liner.

    Args:
        detail: Human-readable message (Persian for user-facing errors).
        code:   Stable snake_case error code (e.g. 'not_found').
    """
    return {"detail": detail, "code": code}
