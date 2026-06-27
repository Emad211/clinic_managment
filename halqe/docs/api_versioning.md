# API Versioning Policy — Halqe Platform

Status: active · Owner: API/platform · Last updated: step 56 (cluster M)

This is the contract between the Halqe backend and every consumer (the Next.js
web app today; a Flutter mobile app and third-party integrations later). It says
what we promise not to break, and how a future v2 is introduced without breaking
v1.

---

## 1. Where v1 lives (the mount boundary)

There is exactly **one** version mounted today: **v1**.

- `config/api_base.py` constructs the single `NinjaAPI` instance:
  `api = NinjaAPI(title="Halqe Platform API", version="0.1.0")`.
- `config/api.py` wires every domain router onto that one `api` with
  `api.add_router(prefix, router)` — auth, patients, vitals, suggestions,
  worklist, encounters, control-room, doctor-queue, engagement, manager,
  patient-card, self-report.
- `config/urls.py` mounts it under the version prefix:
  `path("api/v1/", api.urls)`.

So the version prefix `/api/v1` is owned by the **URLconf**, not by the router
paths. Each domain router carries version-agnostic sub-paths; the `/api/v1`
segment is added once at mount time. The contract guard
(`tests/test_openapi_contract.py`) asserts every operation stays under
`/api/v1/`.

The published surface as of step 56: **44 operations across 42 paths**, locked
by the committed `docs/openapi.json` snapshot (see §5).

---

## 2. The `version` field (`0.1.0`)

`NinjaAPI(version="0.1.0")` is the **OpenAPI `info.version`** — a documentation/
spec marker that appears in `docs/openapi.json` and the generated docs. It is
**independent of the URL version** (`/api/v1`):

- `/api/v1` = the **URL contract version**. It changes only when we cut a v2
  mount (a breaking generation). This is what consumers hard-code.
- `info.version` = the **spec revision** of the v1 surface. Bump it on notable
  additive changes (new endpoints/fields) so docs and changelogs have a handle.
  It does **not** appear in any URL and never forces a client change.

Rule of thumb: bumping `info.version` is cheap and additive; bumping the URL
version (`v1` → `v2`) is a heavyweight, breaking event (§4).

---

## 3. What is allowed WITHIN v1 (additive, non-breaking)

These changes stay in v1 and do **not** require a new version. They will,
however, change `docs/openapi.json`, so you must regenerate the snapshot
(`python manage.py dump_openapi`) and update the locked count in
`tests/test_openapi_contract.py` in the same commit.

Allowed (additive / backward-compatible):

- Adding a **new endpoint** (new path or new verb on an existing path).
- Adding a **new OPTIONAL request field** (with a default; old clients omit it).
- Adding a **new field to a response** (old clients ignore unknown fields).
- Adding a new **enum value** to an output-only field (document it; input enums
  are riskier — see below).
- Relaxing a validation constraint (e.g. widening a max length).
- Pure documentation / description / example changes.

Each of these keeps existing requests valid and existing responses parseable.

---

## 4. What is BREAKING (requires v2)

A breaking change MUST NOT be shipped inside `/api/v1`. It requires a separate
`/api/v2` mount (§6). Breaking includes:

- Removing or renaming an endpoint, path parameter, or response field.
- Changing a field's type or making a previously-optional request field
  required.
- Changing the meaning/units of a field, or tightening validation so previously
  valid requests now 422.
- Changing authentication/permission semantics on an existing route (e.g. making
  a public route require auth, or vice-versa).
- Changing the uniform error contract shape (`{detail, code}`) or the pagination
  envelope (`{items, total, limit, offset}`).

When in doubt: if any existing, conforming consumer could break, it is breaking.

---

## 5. The contract lock (how drift is caught)

The API surface is snapshotted and guarded so accidental contract changes are
caught in review/CI, not in production:

- **Snapshot:** `python manage.py dump_openapi` writes the live
  `api.get_openapi_schema()` to `docs/openapi.json`, pretty-printed with
  `sort_keys=True` and `ensure_ascii=False` for meaningful, stable diffs. The
  committed JSON is the contract artifact reviewers diff.
- **CI drift gate:** `python manage.py dump_openapi --check` exits non-zero if
  the committed snapshot is stale vs the live schema.
- **In-suite guard:** `tests/test_openapi_contract.py` (DB-free) asserts the
  operation count, path count, core paths, version field, public-route presence,
  and that the committed snapshot matches the live schema.

If you make an intentional additive change, the workflow is:
1. change the code,
2. `python manage.py dump_openapi`,
3. update `EXPECTED_OPERATION_COUNT` / `EXPECTED_PATH_COUNT` in the contract
   test,
4. commit code + `docs/openapi.json` + test together.

---

## 6. How a future v2 is introduced (no v1 breakage)

v2 is a **separate `NinjaAPI` instance**, mounted at a separate URL prefix, so
v1 keeps serving its existing consumers untouched:

```python
# config/api_v2.py  (future)
from ninja import NinjaAPI
api_v2 = NinjaAPI(title="Halqe Platform API", version="2.0.0", urls_namespace="v2")
# wire ONLY the routers whose contract changed; unchanged domains can re-use the
# v1 routers verbatim (import and add_router them onto api_v2).

# config/urls.py  (future)
urlpatterns = [
    path("healthz", healthz),
    path("readyz", readyz),
    path("api/v1/", api.urls),       # unchanged — v1 stays exactly as-is
    path("api/v2/", api_v2.urls),    # new surface
]
```

Notes:
- v2 reuses everything it can — only the routers with breaking changes are
  re-authored; stable domains share the v1 routers.
- Each version gets its own contract snapshot
  (`docs/openapi.json` for v1, `docs/openapi_v2.json` for v2) and its own guard
  invariants.
- The JWT auth dependency (`platform_core.auth_bearer.JWTBearer`) and the
  uniform error/pagination helpers are version-agnostic and shared.

---

## 7. Deprecation window

When a v2 ships and a v1 endpoint is destined for removal:

1. **Announce** in the changelog and mark the v1 operation `deprecated: true`
   in its OpenAPI metadata (django-ninja supports `deprecated=True` on the
   operation decorator) so it surfaces in generated docs and the snapshot diff.
2. **Dual-run** v1 and v2 in parallel for a minimum **2 release cycles** (and no
   less than the agreed support window with mobile clients, which cannot be
   force-upgraded as fast as the web app).
3. **Sunset** only after telemetry shows the deprecated v1 endpoints have no
   meaningful traffic from supported clients.

Single-VPS reality (current stage): there is one deployment and one first-party
web client, so a v2 is unlikely before the multi-tenant cloud rollout. This
policy exists so the seam is unambiguous the day it is needed — keeping the
`/api/v{n}` segment in the URLconf (never in router paths) is the key enabler.
