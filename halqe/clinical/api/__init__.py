"""
Domain routers for the Halqe Platform API (cleanup step 3 — god-file split).

Each module under this package owns ONE API domain as a django-ninja ``Router``.
``config.api`` imports each domain's ``router`` and wires it onto the single
``NinjaAPI`` instance with ``api.add_router(prefix, router)`` — preserving the
exact full URL of every endpoint (``/api/v1/...``).

Routers depend on ``config.api_base`` (the ``NinjaAPI`` instance + ``_jwt_auth``),
``config.errors`` and ``config.pagination``.  They never import ``config.api``,
so the package stays free of import cycles.
"""
