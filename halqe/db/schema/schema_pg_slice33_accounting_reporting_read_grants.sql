-- ============================================================================
-- Accounting reporting read-port grants.
--
-- platform_app is the unified Halqe application role: it may write platform and
-- clinical data, but accounting remains physically SELECT-only. The accounting
-- schema intentionally has no blanket default privilege for future tables, so
-- reporting dependencies must be reviewed and granted explicitly.
-- ============================================================================

GRANT SELECT ON TABLE
    accounting.medical_staff,
    accounting.payroll_settings,
    accounting.invoice_item_payments
TO platform_app;

-- These financial, contract and payment-state tables are not part of the
-- clinical identity read port and remain invisible to clinical_app.
REVOKE ALL ON TABLE
    accounting.medical_staff,
    accounting.payroll_settings,
    accounting.invoice_item_payments
FROM clinical_app;
