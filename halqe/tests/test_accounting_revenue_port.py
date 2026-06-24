"""
Tests for accounting_port revenue read functions (Step 13 — financial reads).

Coverage:
  1. get_revenue_by_patient_ids: closed-invoice revenue only (visit+inj+proc).
  2. get_revenue_by_patient_ids: open invoice items are EXCLUDED.
  3. get_revenue_by_patient_ids: since/until filtering on work_date.
  4. get_revenue_by_patient_ids: per-patient grouping (two separate patients).
  5. get_revenue_by_patient_ids: unknown patient_id → absent from result dict.
  6. get_patient_revenue_summary: total_billed + invoice_count + last_visit_date.
  7. get_patient_revenue_summary: patient with no closed invoices → None.
  8. get_daily_revenue_by_patient_ids: revenue grouped by work_date.
  9. All reads go through 'accounting_read' — no accounting write attempted.
     (the DB-level boundary is already proven by test_db_boundary.py; we simply
     confirm the port functions succeed on accounting_read without raising.)

Seed strategy:
  - Uses SUPERUSER psycopg (same pattern as conftest.py seed_data) — the app
    role (platform_app / platform_login_test) cannot write to accounting.*.
  - Seeds two accounting patients with invoices, visits, injections, procedures.
  - Seeds ONE open invoice (to verify exclusion) and ONE closed invoice.
  - Session-scoped so setup runs once; individual tests are read-only.

Connection note:
  - The port functions internally use connections["accounting_read"].cursor().
  - This is the same least-privilege role Django uses; SELECT is allowed.
  - No accounting write is performed anywhere in this module.
"""
import os
import pytest
import psycopg

# ---------------------------------------------------------------------------
# Superuser conninfo for seed (same pattern as conftest.py)
# ---------------------------------------------------------------------------
_PG_HOST     = os.environ.get("PG_HOST", "localhost")
_PG_PORT     = os.environ.get("PG_PORT", "55432")
_PG_TEST_DB  = os.environ.get("PG_TEST_DB", "halqe_app_test")
_PG_SU_USER  = os.environ.get("PG_USER", "postgres")
_PG_SU_PW    = os.environ.get("PG_PASSWORD", "validate_only")


def _su_conn():
    """Open a superuser psycopg connection to the test DB (for seed only)."""
    return psycopg.connect(
        f"host='{_PG_HOST}' port='{_PG_PORT}' "
        f"user='{_PG_SU_USER}' password='{_PG_SU_PW}' dbname='{_PG_TEST_DB}'",
        autocommit=True,
    )


# ---------------------------------------------------------------------------
# Session-scoped seed fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def revenue_seed(django_db_setup):
    """
    Seed two accounting patients with invoices + items for revenue tests.

    Patient A: ONE closed invoice with visit (100 000) + injection (50 000)
               + procedure (30 000) → total 180 000 Toman.
               work_date = '2024-03-10' (within range tests will use).
               ALSO: ONE open invoice with a visit (999 000) — must be excluded.

    Patient B: ONE closed invoice with visit (200 000) only, work_date='2024-01-05'.

    Returns dict of IDs and expected amounts.
    """
    with _su_conn() as conn:
        import uuid as _uuid

        # ── Patient A ─────────────────────────────────────────────────────────
        pa_uuid = _uuid.uuid4()
        conn.execute(
            """
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id)
            VALUES (1, %s, 'رضا', 'محمدی', '5550001111')
            ON CONFLICT (uuid) DO NOTHING
            """,
            (pa_uuid,),
        )
        pa_id = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s", (pa_uuid,)
        ).fetchone()[0]

        # Closed invoice A — the revenue invoice
        conn.execute(
            """
            INSERT INTO accounting.invoices
                (tenant_id, patient_id, status, work_date, total_amount)
            VALUES (1, %s, 'closed', '2024-03-10', 180000)
            """,
            (pa_id,),
        )
        closed_inv_a = conn.execute(
            "SELECT id FROM accounting.invoices "
            "WHERE patient_id=%s AND status='closed' ORDER BY id DESC LIMIT 1",
            (pa_id,),
        ).fetchone()[0]

        conn.execute(
            "INSERT INTO accounting.visits (tenant_id, patient_id, invoice_id, price) "
            "VALUES (1, %s, %s, 100000)",
            (pa_id, closed_inv_a),
        )
        conn.execute(
            "INSERT INTO accounting.injections "
            "  (tenant_id, patient_id, invoice_id, injection_type, total_price, unit_price) "
            "VALUES (1, %s, %s, 'آمپول', 50000, 50000)",
            (pa_id, closed_inv_a),
        )
        conn.execute(
            "INSERT INTO accounting.procedures "
            "  (tenant_id, patient_id, invoice_id, procedure_type, price) "
            "VALUES (1, %s, %s, 'پانسمان', 30000)",
            (pa_id, closed_inv_a),
        )

        # Open invoice A — items here must NOT appear in revenue totals
        conn.execute(
            """
            INSERT INTO accounting.invoices
                (tenant_id, patient_id, status, work_date, total_amount)
            VALUES (1, %s, 'open', '2024-03-11', 999000)
            """,
            (pa_id,),
        )
        open_inv_a = conn.execute(
            "SELECT id FROM accounting.invoices "
            "WHERE patient_id=%s AND status='open' ORDER BY id DESC LIMIT 1",
            (pa_id,),
        ).fetchone()[0]

        conn.execute(
            "INSERT INTO accounting.visits (tenant_id, patient_id, invoice_id, price) "
            "VALUES (1, %s, %s, 999000)",
            (pa_id, open_inv_a),
        )

        # ── Patient B ─────────────────────────────────────────────────────────
        pb_uuid = _uuid.uuid4()
        conn.execute(
            """
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id)
            VALUES (1, %s, 'نگین', 'احمدی', '5550002222')
            ON CONFLICT (uuid) DO NOTHING
            """,
            (pb_uuid,),
        )
        pb_id = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s", (pb_uuid,)
        ).fetchone()[0]

        conn.execute(
            """
            INSERT INTO accounting.invoices
                (tenant_id, patient_id, status, work_date, total_amount)
            VALUES (1, %s, 'closed', '2024-01-05', 200000)
            """,
            (pb_id,),
        )
        closed_inv_b = conn.execute(
            "SELECT id FROM accounting.invoices "
            "WHERE patient_id=%s AND status='closed' ORDER BY id DESC LIMIT 1",
            (pb_id,),
        ).fetchone()[0]

        conn.execute(
            "INSERT INTO accounting.visits (tenant_id, patient_id, invoice_id, price) "
            "VALUES (1, %s, %s, 200000)",
            (pb_id, closed_inv_b),
        )

    return {
        "pa_id": pa_id,
        "pb_id": pb_id,
        "closed_inv_a": closed_inv_a,
        "open_inv_a": open_inv_a,
        "closed_inv_b": closed_inv_b,
        # Expected revenue totals
        "pa_total": 180_000,    # visit(100k) + injection(50k) + procedure(30k)
        "pa_visit": 100_000,
        "pa_injection": 50_000,
        "pa_procedure": 30_000,
        "pb_total": 200_000,
        "pa_work_date": "2024-03-10",
        "pb_work_date": "2024-01-05",
    }


# ---------------------------------------------------------------------------
# 1. Closed-invoice revenue: visit + injection + procedure summed correctly
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_revenue_closed_invoice_sums_all_item_types(revenue_seed):
    """
    get_revenue_by_patient_ids returns visit+injection+procedure of the CLOSED
    invoice; open invoice items are excluded.
    """
    from accounting_port.port import get_revenue_by_patient_ids

    pa_id = revenue_seed["pa_id"]
    result = get_revenue_by_patient_ids([pa_id])

    assert pa_id in result, "Patient A should appear in the result"
    assert result[pa_id] == revenue_seed["pa_total"], (
        f"Expected {revenue_seed['pa_total']}, got {result[pa_id]}"
    )


# ---------------------------------------------------------------------------
# 2. Open invoice items must be excluded
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_revenue_open_invoice_items_are_excluded(revenue_seed):
    """
    The open invoice has a visit of 999 000 Toman. The result must NOT include it.
    Patient A closed total = 180 000 (not 1 179 000).
    """
    from accounting_port.port import get_revenue_by_patient_ids

    pa_id = revenue_seed["pa_id"]
    result = get_revenue_by_patient_ids([pa_id])

    assert result.get(pa_id, 0) == revenue_seed["pa_total"], (
        f"Open invoice items leaked into revenue: got {result.get(pa_id)}, "
        f"expected {revenue_seed['pa_total']}"
    )
    assert result.get(pa_id, 0) != 1_179_000, "Open invoice visit was incorrectly included"


# ---------------------------------------------------------------------------
# 3. since / until filtering on work_date
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_revenue_since_filter_excludes_earlier_dates(revenue_seed):
    """
    since='2024-02-01' should include patient A (2024-03-10) but exclude B (2024-01-05).
    """
    from accounting_port.port import get_revenue_by_patient_ids

    pa_id = revenue_seed["pa_id"]
    pb_id = revenue_seed["pb_id"]
    result = get_revenue_by_patient_ids([pa_id, pb_id], since="2024-02-01")

    assert pa_id in result, "Patient A (2024-03-10) should be included with since=2024-02-01"
    assert pb_id not in result, (
        "Patient B (2024-01-05) should be excluded with since=2024-02-01"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_revenue_until_filter_excludes_later_dates(revenue_seed):
    """
    until='2024-02-01' should include patient B (2024-01-05) but exclude A (2024-03-10).
    """
    from accounting_port.port import get_revenue_by_patient_ids

    pa_id = revenue_seed["pa_id"]
    pb_id = revenue_seed["pb_id"]
    result = get_revenue_by_patient_ids([pa_id, pb_id], until="2024-02-01")

    assert pb_id in result, "Patient B (2024-01-05) should be included with until=2024-02-01"
    assert pa_id not in result, (
        "Patient A (2024-03-10) should be excluded with until=2024-02-01"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_revenue_since_until_inclusive_bounds(revenue_seed):
    """
    Exact date match: since=until='2024-03-10' should return only patient A.
    Both bounds are inclusive.
    """
    from accounting_port.port import get_revenue_by_patient_ids

    pa_id = revenue_seed["pa_id"]
    pb_id = revenue_seed["pb_id"]
    result = get_revenue_by_patient_ids(
        [pa_id, pb_id], since="2024-03-10", until="2024-03-10"
    )

    assert pa_id in result
    assert pb_id not in result
    assert result[pa_id] == revenue_seed["pa_total"]


# ---------------------------------------------------------------------------
# 4. Per-patient grouping — two patients, separate totals
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_revenue_per_patient_grouping(revenue_seed):
    """
    Batch query for two patients returns separate totals per patient_id.
    """
    from accounting_port.port import get_revenue_by_patient_ids

    pa_id = revenue_seed["pa_id"]
    pb_id = revenue_seed["pb_id"]
    result = get_revenue_by_patient_ids([pa_id, pb_id])

    assert result.get(pa_id) == revenue_seed["pa_total"], (
        f"Patient A: expected {revenue_seed['pa_total']}, got {result.get(pa_id)}"
    )
    assert result.get(pb_id) == revenue_seed["pb_total"], (
        f"Patient B: expected {revenue_seed['pb_total']}, got {result.get(pb_id)}"
    )


# ---------------------------------------------------------------------------
# 5. Unknown patient_id → absent from result dict (treat as 0)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_revenue_unknown_patient_id_is_absent(revenue_seed):
    """
    A patient_id that does not exist in accounting should produce no entry in
    the result dict (not an error, not a 0 entry — just absent).
    """
    from accounting_port.port import get_revenue_by_patient_ids

    ghost_id = 9_999_999  # guaranteed to not exist
    result = get_revenue_by_patient_ids([ghost_id])

    assert ghost_id not in result, (
        f"Unknown patient {ghost_id} should not appear in result; got {result}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_revenue_empty_ids_list_returns_empty_dict(revenue_seed):
    """Edge case: empty input → empty dict, no DB round-trip."""
    from accounting_port.port import get_revenue_by_patient_ids

    result = get_revenue_by_patient_ids([])
    assert result == {}


# ---------------------------------------------------------------------------
# 6. get_patient_revenue_summary: total_billed + invoice_count + last_visit_date
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_revenue_summary_patient_a(revenue_seed):
    """
    Patient A: 1 closed invoice, total=180 000, last_visit_date='2024-03-10'.
    """
    from accounting_port.port import get_patient_revenue_summary

    pa_id = revenue_seed["pa_id"]
    summary = get_patient_revenue_summary(pa_id)

    assert summary is not None, "Expected a summary for patient A"
    assert summary.accounting_patient_id == pa_id
    assert summary.total_billed == revenue_seed["pa_total"]
    assert summary.invoice_count == 1
    assert summary.last_visit_date == revenue_seed["pa_work_date"]


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_revenue_summary_patient_b(revenue_seed):
    """
    Patient B: 1 closed invoice, total=200 000, last_visit_date='2024-01-05'.
    """
    from accounting_port.port import get_patient_revenue_summary

    pb_id = revenue_seed["pb_id"]
    summary = get_patient_revenue_summary(pb_id)

    assert summary is not None
    assert summary.total_billed == revenue_seed["pb_total"]
    assert summary.invoice_count == 1
    assert summary.last_visit_date == revenue_seed["pb_work_date"]


# ---------------------------------------------------------------------------
# 7. Patient with no closed invoices → None
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_revenue_summary_no_closed_invoices_returns_none(revenue_seed):
    """
    A patient_id with no closed invoices (or no invoices at all) should return None.
    """
    from accounting_port.port import get_patient_revenue_summary

    ghost_id = 9_999_998
    summary = get_patient_revenue_summary(ghost_id)
    assert summary is None, f"Expected None for ghost patient, got {summary}"


# ---------------------------------------------------------------------------
# 8. get_daily_revenue_by_patient_ids: revenue grouped by work_date
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_daily_revenue_groups_by_date(revenue_seed):
    """
    Daily trend for both patients in range 2024-01-01..2024-12-31.
    Expects '2024-03-10' → 180 000 and '2024-01-05' → 200 000.
    (May have more dates from other tests' seeds; we check containment only.)
    """
    from accounting_port.port import get_daily_revenue_by_patient_ids

    pa_id = revenue_seed["pa_id"]
    pb_id = revenue_seed["pb_id"]
    daily = get_daily_revenue_by_patient_ids([pa_id, pb_id], "2024-01-01", "2024-12-31")

    assert isinstance(daily, dict)
    assert "2024-03-10" in daily, "Expected revenue on 2024-03-10 for patient A"
    assert daily["2024-03-10"] >= revenue_seed["pa_total"], (
        f"2024-03-10 total should be >= {revenue_seed['pa_total']}, got {daily['2024-03-10']}"
    )
    assert "2024-01-05" in daily, "Expected revenue on 2024-01-05 for patient B"
    assert daily["2024-01-05"] >= revenue_seed["pb_total"], (
        f"2024-01-05 total should be >= {revenue_seed['pb_total']}, got {daily['2024-01-05']}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_daily_revenue_excludes_dates_outside_range(revenue_seed):
    """
    Narrow range 2024-03-01..2024-03-31 should only contain March dates.
    Patient B's 2024-01-05 must be absent.
    """
    from accounting_port.port import get_daily_revenue_by_patient_ids

    pa_id = revenue_seed["pa_id"]
    pb_id = revenue_seed["pb_id"]
    daily = get_daily_revenue_by_patient_ids([pa_id, pb_id], "2024-03-01", "2024-03-31")

    assert "2024-01-05" not in daily, (
        "2024-01-05 is outside the requested range and must be absent"
    )
    assert "2024-03-10" in daily


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_daily_revenue_empty_ids_returns_empty(revenue_seed):
    """Edge case: empty patient list → empty dict."""
    from accounting_port.port import get_daily_revenue_by_patient_ids

    result = get_daily_revenue_by_patient_ids([], "2024-01-01", "2024-12-31")
    assert result == {}


# ---------------------------------------------------------------------------
# 9. Confirm reads go through accounting_read (no PermissionError raised)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_port_reads_succeed_via_accounting_read(revenue_seed):
    """
    All three port functions complete successfully, confirming the accounting_read
    connection provides SELECT access as required by slice-3 GRANTs.
    """
    from accounting_port.port import (
        get_revenue_by_patient_ids,
        get_patient_revenue_summary,
        get_daily_revenue_by_patient_ids,
    )

    pa_id = revenue_seed["pa_id"]

    # Should not raise — accounting_read has SELECT on accounting.*
    rev = get_revenue_by_patient_ids([pa_id])
    assert isinstance(rev, dict)

    summary = get_patient_revenue_summary(pa_id)
    assert summary is not None

    daily = get_daily_revenue_by_patient_ids([pa_id], "2024-01-01", "2024-12-31")
    assert isinstance(daily, dict)
