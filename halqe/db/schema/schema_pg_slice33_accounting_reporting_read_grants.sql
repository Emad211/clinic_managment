-- ============================================================================
-- Accounting reporting read-port grants.
--
-- platform_app is the unified Halqe application role: it may write platform and
-- clinical data, but accounting remains physically SELECT-only.  The accounting
-- schema intentionally has no blanket default privilege for future tables, so
-- reporting dependencies must be reviewed and granted explicitly.
-- ============================================================================

GRANT SELECT ON TABLE
    accounting.medical_staff,
    accounting.payroll_settings
TO platform_app;

-- Do not grant these financial/contract tables to clinical_app.  Clinical code
-- reaches accounting identity through narrowly-scoped read ports only.
REVOKE ALL ON TABLE
    accounting.medical_staff,
    accounting.payroll_settings
FROM clinical_app;
