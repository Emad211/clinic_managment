# ArvanCloud CDN — setup notes for halqe (halqehealth.ir)

Distilled from the official docs (read 2026-07-04). This is the durable record of
HOW we put `halqehealth.ir` behind ArvanCloud CDN and the decisions we made.

> 📌 **Reference hub (always come back here): https://docs.arvancloud.ir/fa/**
> Key pages: [CDN](https://docs.arvancloud.ir/fa/cdn) ·
> [HTTPS settings](https://docs.arvancloud.ir/fa/cdn/https-settings) ·
> [Security](https://docs.arvancloud.ir/fa/cdn/security) ·
> [Whitelist edge IPs](https://docs.arvancloud.ir/fa/cdn/domain/whitelist) ·
> **Edge IP ranges: https://www.arvancloud.ir/fa/ips**

## Where we are

- Domain `halqehealth.ir` registered (IRNIC), Arvan CDN "رشد" pay-as-you-go activated.
- Arvan nameservers (set these at IRNIC): **`g.ns.arvancdn.ir`** + **`s.ns.arvancdn.ir`**.
- A record created in Arvan DNS: `@` → `95.38.187.128`, **cloud/proxy ON** (نماد ابر روشن).
- Pending: change NS at IRNIC → wait for `.ir` propagation → Arvan "بررسی مجدد" verifies.

## TLS — two hops (edge↔user and edge↔origin)

**1. Edge ↔ user (Arvan panel → دامنه → HTTPS/SSL):**
- Enable HTTPS; use the **free Let's Encrypt cert** (3-month, auto-renew) — Arvan manages it.
  Users get a real green-padlock cert for `halqehealth.ir`; our origin self-signed is never
  shown to users.
- Turn on **HTTPS redirect** (`https_redirect`) so HTTP→HTTPS.
- **HSTS**: enable only AFTER HTTPS is confirmed permanent (once on + cached, it's sticky).
- Min TLS: leave default (Arvan supports TLS 1.3). HTTP/3+QUIC optional (perf).

**2. Edge ↔ origin (Arvan panel → «پروتکل ارتباطی سرورهای لبه و سرور اصلی»):** 3 modes —
`auto` / `http` (port 80, PLAINTEXT) / `https` (port 443, needs a cert on origin).
- **Decision: set to `https`.** For health PHI the CDN→origin hop MUST be encrypted (the
  security review flagged edge-only TLS as insufficient). Our nginx already listens on 443
  with a self-signed cert, which satisfies "https" mode. Do NOT use `auto`/`http`.
- **Optional upgrade (cleaner for PHI):** Arvan can issue a real **origin server certificate**
  (panel → «گواهی‌نامه‌ی سرور اصلی», 3 free/month, needs the domain active + a cloud-enabled
  DNS record). Install it on nginx to replace the self-signed. Nice-to-have, not blocking.

## Security modules (Arvan panel → امنیت) — require cloud ON

Execution order: **1. Firewall → 2. DDoS → 3. Rate Limit → 4. WAF.**

- **Arvan Rate Limit**: applies ONLY to non-cached / non-cacheable requests (our /api/v1/* are
  non-cacheable → it WOULD apply). **Decision: leave Arvan's rate-limit OFF for now** — our
  nginx already enforces the sacred card/self-report limit. Enabling both risks confusing
  double-limiting. Revisit later if we want an edge-layer cap.
- **WAF**: "تنظیمات نادرست WAF می‌تواند دسترسی به سایت را مختل کند." **Decision: WAF OFF
  initially** — a mis-tuned WAF can break the JSON API. Enable later with a careful ruleset.
- **DDoS protection**: fine to keep at Arvan's default.
- **Firewall (Arvan CDN)**: can block by country/IP — optional; not needed for the pilot.

## ⚠️ The #1 origin change we MUST make (the real_ip risk)

Behind the CDN, every request to our origin arrives from an **Arvan edge IP**, not the real
patient. Our nginx keys the sacred rate-limit on `$binary_remote_addr`
(`deploy/nginx/halqe.conf:51`), so without a fix ALL patients bucket under one edge IP.

**Fix (orchestrator does this once we have the ranges):** add the Arvan edge ranges to
`set_real_ip_from` in `deploy/nginx/halqe.conf:82-87` so nginx trusts Arvan's `X-Forwarded-For`
and extracts the real client IP. Then re-test the 429 burst from an EXTERNAL network via the
domain.

## Origin firewall — hide the origin (whitelist edge IPs)

Per the whitelist doc: the origin must accept traffic ONLY from Arvan edge IPs (else an
attacker hits `95.38.187.128` directly and bypasses the CDN/WAF/rate-limit). Restrict the
**Arvan security-group** inbound `80/443` to the edge ranges from
https://www.arvancloud.ir/fa/ips (Docker bypasses UFW, so use the security-group). `22` stays
as-is; `8000/5432` stay unpublished.

> ⚠️ **Never fabricate the edge ranges** — copy the live list from arvancloud.ir/fa/ips (it is
> kept updated). Getting them wrong either locks out the CDN or leaves the origin exposed.

## Origin-side app config (orchestrator, after NS propagates)

- `.env`: `ALLOWED_HOSTS=halqehealth.ir,95.38.187.128,127.0.0.1,localhost` (durable in
  `gen_staging_env.sh` too).
- nginx `server_name _;` already accepts any Host — no change needed there.
- `set_real_ip_from` + Arvan edge ranges (above).
- CORS stays empty (same-origin behind one nginx — web + api on one hostname).

## Handy Arvan CDN API (napi.arvancloud.ir/cdn/4.0) — for later automation

`PATCH /domains/<d>/ssl` → `{ssl_status|https_redirect|replace_http|tls_version|hsts_*}` ·
`PATCH /domains/<d>/load-balancers/settings` → `{"protocol":"http|https|auto"}` (edge↔origin).
