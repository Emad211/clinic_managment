# Observability — Halqe Platform

Status: active · Owner: API/platform · Last updated: step 56 (cluster M)

This documents the EXISTING observability story (built in step 28, tested in
`tests/test_observability.py`). It is a reference for operators and developers —
nothing here is new infrastructure except the two minimal, additive log
enhancements called out in §6 (gunicorn request-id in the access log + Docker
log rotation). The health probes, request-id middleware, and structured logging
were already in place; this doc explains how to read and operate them.

---

## 1. Health probes — `/healthz` and `/readyz`

Defined in `platform_core/health.py`, mounted at the URL **root** (not under
`/api/v1`) in `config/urls.py` so load-balancers and the compose healthcheck can
reach them with no path prefix and no auth.

### `/healthz` — liveness
- **Always 200** `{"status": "ok"}`.
- **No DB, no auth, no middleware that needs a DB.** It only confirms the Python
  process accepted the connection and can run a view.
- Used by the compose healthcheck (`docker-compose.yml` → `app.healthcheck`,
  every 15s) and is the right probe for a load-balancer liveness check.
- A liveness failure means "restart the container" — so it must NOT depend on
  the DB (a DB outage should not trigger app restarts).

### `/readyz` — readiness
- Runs `SELECT 1` on the **`default`** (primary) DB connection.
- **200** `{"status": "ready"}` when the check passes.
- **503** `{"status": "not_ready", "reason": "primary database unavailable"}`
  on any DB error. The internal exception is **logged server-side** (logger
  `platform_core.health`, ERROR with `exc_info`) but the **reason returned to
  the caller is generic** — no DB hostnames, passwords, or exception text leak.
- The `accounting_read` alias is **deliberately NOT checked**: it is an optional,
  read-only bridge; its unavailability must not block clinical writes or fail
  readiness.
- `SELECT 1` touches no tenant table, so it is safe under RLS fail-closed without
  setting the `app.current_tenant` GUC.

**When is each 200 vs 503?**

| Condition                          | `/healthz` | `/readyz`        |
|------------------------------------|-----------|------------------|
| Process up, DB up                  | 200       | 200 `ready`      |
| Process up, primary DB down/slow   | 200       | 503 `not_ready`  |
| Process down / not accepting conns | (no resp) | (no resp)        |
| accounting_read bridge down        | 200       | 200 `ready`      |

Use `/healthz` for "should I restart this?" and `/readyz` for "should I route
traffic here?". The compose healthcheck uses `/healthz` on purpose — a DB blip
should not flap the app container.

---

## 2. Request correlation — `X-Request-ID`

Defined in `platform_core/request_id.py` (`RequestIdMiddleware`), wired FIRST in
`settings.MIDDLEWARE` so it runs before `TenantGucMiddleware` and every view.

Flow for every request:
1. Read the incoming `X-Request-ID` header.
2. **Sanitize** it: accept only `[a-zA-Z0-9-_]`, 1–64 chars. Anything else
   (too long, bad charset, empty/absent) → a fresh **uuid4** is generated. (Bad
   input never causes a 400 — health probes that send garbage still get
   200/503.)
3. Store the clean ID on `request.request_id` AND in a module-level
   **contextvar** (`_request_id_ctx_var`).
4. **Echo it back** on the response as `X-Request-ID`.
5. Reset the contextvar in a `finally` — defends against thread/connection reuse
   leaking one request's ID into another.

`RequestIdFilter` (a `logging.Filter`) reads the contextvar and injects
`request_id` into **every** `LogRecord`. Outside a request (management commands,
background scheduler threads) it defaults to `-`, so log lines are always
well-formed.

**Operator tip:** when a client reports an error, ask for the `X-Request-ID`
from the response headers, then grep the logs for that exact id to see every log
line for that one request (across Django logs and — after §6 — the gunicorn
access line too).

---

## 3. Structured, PII-free logging

Configured in `settings.LOGGING` (step 28). Two modes gated by the `PRODUCTION`
env var:

- **Dev** (`PRODUCTION` unset): human-readable
  `time | LEVEL | logger | [request_id] message`, DEBUG level. Colour if
  `colorlog` is installed, else plain text.
- **Production** (`PRODUCTION=1`): single-line **key=value** structured format,
  machine-parseable by log aggregators (Loki/ELK/CloudWatch):
  `time=… level=… logger=… request_id=… message=…`, INFO+ (DEBUG suppressed).

Handler: a single `console` `StreamHandler` (stdout) with the `request_id`
filter attached. App loggers (`platform_core`, `clinical`, `accounting_port`,
`config`) propagate=False at the level above; root is WARNING+ for third-party
noise.

### PII-free contract
Enforced at the **caller** level — the logging config cannot scrub what callers
pass in, so the rule is: logging must NEVER receive
- request/response bodies,
- `national_id`, `password`, raw token values,
- any field whose name ends in `_hash` or `_token`.

The health probe's 503 path is the canonical example: it logs `exc_info`
server-side but returns only a generic reason to the client.

---

## 4. Where logs go (gunicorn / compose / VPS)

In production the app runs under **gunicorn** (see `entrypoint.sh`):
`gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-3}
--timeout 120 --access-logfile - --error-logfile - --access-logformat "…"`.

- gunicorn streams its **access log** and **error log** to **stdout/stderr**
  (`-`), and Django's structured `console` handler also writes to stdout.
- Under `docker-compose.yml`, the `app` container's stdout/stderr is captured by
  Docker's **json-file** logging driver (now bounded — §6).
- The app container is **internal-only** (no `ports:` mapping); **nginx** is the
  sole public ingress and the real rate-limit boundary for public patient
  endpoints.

### Reading logs on the VPS
```sh
cd halqe                       # where docker-compose.yml lives
docker compose logs -f app     # follow live app logs (gunicorn + Django)
docker compose logs --since=1h app
docker compose logs app | grep 'rid=<the-request-id>'   # one request, end to end
docker compose logs nginx      # ingress / rate-limit / TLS layer
```
To trace one request: take the `X-Request-ID` from the client's response, then
grep for `request_id=<id>` (Django lines) and `rid=<id>` (gunicorn access line).

---

## 5. What is intentionally NOT here (deferred)

- **Prometheus `/metrics` + a scraper.** Deferred. At the single-VPS stage there
  is no scraper to consume it; adding an endpoint with nothing reading it is dead
  weight. When the deployment grows beyond one VPS (multi-tenant cloud), add a
  `/metrics` endpoint (e.g. `django-prometheus` or a hand-rolled exporter) and a
  Prometheus/Grafana stack. The request-id + structured-log foundation already
  in place is what those metrics would correlate against.
- **Distributed tracing (OpenTelemetry).** Same rationale — deferred until there
  is more than one service to trace across. `X-Request-ID` is the lightweight
  stand-in for now.
- **Centralized log aggregation (Loki/ELK).** The production `key=value` format
  is already aggregator-ready; standing up the aggregator is a later-stage op.

---

## 6. Minimal enhancements added in step 56 (verified non-duplicate)

Both are additive ops-config changes — no application code, no API surface
change, no new logging framework. Verified absent before adding.

1. **Request-id + latency in the gunicorn access log** (`entrypoint.sh`).
   gunicorn's default access log already carries method/path/status, but NOT the
   correlation id and not (by default) response time in a parseable spot. Added
   `--access-logformat '%(h)s "%(r)s" %(s)s %(b)s %(L)s rid=%({x-request-id}o)s'`:
   - `%(r)s` request line (method + path + protocol),
   - `%(s)s` status, `%(b)s` response size,
   - `%(L)s` request latency in **seconds**,
   - `rid=%({x-request-id}o)s` the **response** `X-Request-ID` (the `o` variant
     — always set by the middleware, even when the request omitted the header),
     so the access line joins to the Django `request_id=…` lines.
   PII-free: only the request LINE is logged — never headers (Authorization,
   cookies) or any body.

2. **Bounded Docker logs for the `app` service** (`docker-compose.yml`).
   Docker's json-file driver is unbounded by default; on a single VPS that can
   silently fill the disk. Added `logging: { driver: json-file, options:
   { max-size: "20m", max-file: "5" } }` to the `app` service (cap ~100 MB,
   rotated). `docker compose logs app` still reads them. Consider applying the
   same cap to `nginx`/`postgres`/`backup` if their volume grows.

These keep liveness/readiness, the request-id flow, and the PII-free structured
logging exactly as they were — they just make the production access log
correlatable and the on-disk footprint bounded.
