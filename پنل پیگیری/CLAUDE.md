# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**پنل پیگیری (Peygiri Panel)** is a standalone patient follow-up app that runs next to the clinic's accounting app (`../webapp`, HesabdariSib.exe). It does four things:
- puts each patient who needs follow-up into a *journey* (prescription renewal, quarterly lab, BP/BS control series, lab order, wound care, ear wax, invite-to-visit);
- schedules calls for reception;
- detects the patient's return from payments recorded in accounting;
- reads accounting **strictly read-only**.

**Status:** M0 committed (`92307517`). M1 implemented and locally verified: poller, mirror, two-source login, doctor accounts/queue, shift override, sync indicator. App 0.2.0, panel schema v2; v1 upgrades take a backup and add `acc_item.item_at`. 169 tests pass, 2 production-copy perf checks skip without `PEYGIRI_PERF_DB`. Next: M2 (identity). See `docs/m1-verification.md` and `docs/08` §1. Read `README.md`, then `docs/01`–`09` in order. Every decision and its source is in `docs/09-decisions-log.md` (IDs `Dxx` decisions, `Axx` assumptions, `Oxx` open items). Rationale is in `docs/adr/`.

## Hard rules

1. **Accounting DB is read-only and touched by one module.** Only `src/adapters/accounting/` may open `clinic_new.db`, and only as specified in `docs/03-accounting-bridge.md`:
   - **Connection:** URI `file:…?mode=ro` plus `PRAGMA query_only=ON`; `isolation_level=None`; SQLite `timeout=0` with a 250 ms wall-clock busy retry in Python (then skip the cycle); close the connection after every cycle.
   - **Per cycle:** exactly one explicit read transaction, with a 200 ms `set_progress_handler` budget.
   - **Queries:** only the ones listed in 03 §5, with explicit columns and PK/index plans only. Any new query must be added to that table and pass the query-plan test.
   - **Never:** write statements or writing PRAGMAs, switching to WAL, `immutable`/`nolock`, `ATTACH`, copying the file, or opening the real file in dev or tests.
   - **Why:** the accounting DB runs `journal_mode=DELETE`. A long-held SHARED lock makes reception's commits fail with "database is locked" after 5 s.
2. **Never import from `../webapp` or `../specialist_clinic`.** `webapp`'s `get_db()` runs migrations (ALTER/CREATE INDEX/UPDATE) on first connect, which means writing to production.
3. **Read from the mirror, not from accounting.** Web routes and services read only the panel DB, including its `acc_*` mirror tables. The only accounting reads outside the poller are login lookup and national-ID lookup, and both go through the bridge.
4. **Identity gate.** No journey becomes `active` without valid identity: a real full name (not placeholders like «خ»/«ا»), a checksum-valid 10-digit national ID, and an `09…` mobile. Identity completed in the panel is never written back to accounting. Foreign nationals are out of scope.
5. **Defaults are data.** Journey templates, defaults and call texts are versioned rows, not code. Clinical cut-offs have **no numeric defaults**, and only a doctor account flagged as director can approve them.
6. **No production data in the repo.** The clinic DB copy is PHI.
   - Tests use synthetic accounting DBs built from the production DDL.
   - Perf tests read a local copy via `PEYGIRI_PERF_DB` and skip when it is unset.
   - Some free-text procedure names contain patient names; sanitize them before using them as fixtures.

## Architecture in brief

- **Process:** one process (`PeygiriPanel.exe`, port 8091) running:
  - the Flask web app (threaded werkzeug, like accounting);
  - a poller thread (every 5 s; id watermarks plus a watched set of open invoices);
  - an engine tick (every 60 s);
  - a weekly backup.
- **Panel DB:** `peygiri_panel.db`, SQLite in WAL mode.
- **Layering:** `api → services → domain` (pure; time is injected) and `adapters` (all SQL). `sync/` holds the poller and the mirror differ, which emits domain events.
- **Journey engine** (`docs/05`):
  - JSON templates with `call` and `expect` steps.
  - **Return** = a paid item of the expected category on a later, non-origin invoice of the same person. A closed zero-total invoice also counts.
  - Evidence is revoked when accounting deletes the item or unmarks its payment.
- **Auth:**
  - Reception and manager log in with accounting `users` credentials (read-only bcrypt check).
  - Doctors use local accounts linked to `medical_staff.id`, verified active in accounting at every login.
- **Schema drift:** the production accounting schema is older than this repo's `webapp` HEAD (no `users.staff_id`, no doctor role). Rely only on the columns in 03 §6. The schema is checked at startup and hourly.

## Conventions

- Persian RTL UI, Jalali dates in the UI, Gregorian in the DB.
- Tehran time is a fixed UTC+3:30, computed from UTC (never naive local `now()`). Timestamps use `YYYY-MM-DD HH:MM:SS`.
- Persian text normalization and procedure keyword classification follow 03 §9.
- Internal names are ASCII (`src/`, `PeygiriPanel.exe`, `peygiri_panel.db`, `config.ini`) even though this folder's name is Persian with a space. Quote the path in shells.

## Commands

Python 3.13 venv in `.venv` (`py -3.13 -m venv .venv`, then `pip install -r requirements-dev.txt`). Quote the folder path in shells.

```powershell
.\.venv\Scripts\python.exe start.py                      # http://127.0.0.1:8091 — creates config.ini on first run
.\.venv\Scripts\python.exe -m pytest tests -q            # ~70 s; bridge + real-poller lock tests dominate
$env:PEYGIRI_PERF_DB = "<path to a COPY of clinic_new.db>"; .\.venv\Scripts\python.exe -m pytest tests\test_perf.py -s
.\.venv\Scripts\python.exe -m PyInstaller PeygiriPanel.spec --noconfirm   # dist\PeygiriPanel.exe
```

- Tests never open a real accounting file: `tests/conftest.py` installs a path guard (temp dirs and `PEYGIRI_PERF_DB` only) and checks `tests/fixtures` hashes. Synthetic accounting DBs come from `tests/accounting_factory.py`, built on the production DDL in `tests/fixtures/accounting_schema.sql` (schema only).
- `tests/test_bridge_safety.py` is the merge gate for `adapters/accounting/` and `sync/`; `tests/test_architecture.py` enforces the layering rules on the AST.
- Gotchas found in M0: SQLite's busy handler on Windows rounds sleeps up to the timer tick, so the bridge uses `timeout=0` and retries in Python (D30); werkzeug calls `sys.exit(1)` (not `OSError`) when the port is taken; a PyInstaller onefile exe shows two processes (bootloader + app).
