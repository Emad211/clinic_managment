-- ============================================================================
-- Accounting write-side provenance — financial safety gate.
--
-- Existing/migrated invoices default to ``legacy``. New Halqe command paths
-- stamp an explicit pricing version. A close command may only recalculate an
-- invoice whose pricing version it understands, preventing historical SQLite
-- rows from being silently reinterpreted under new tariff rules.
-- ============================================================================

ALTER TABLE accounting.invoices
    ADD COLUMN IF NOT EXISTS pricing_version TEXT NOT NULL DEFAULT 'legacy';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'accounting.invoices'::regclass
          AND conname = 'chk_invoices_pricing_version_not_blank'
    ) THEN
        ALTER TABLE accounting.invoices
            ADD CONSTRAINT chk_invoices_pricing_version_not_blank
            CHECK (btrim(pricing_version) <> '');
    END IF;
END
$$;

-- The accounting command role needs the altered table; clinical/platform remain
-- read-only. Revoke platform table reads from the writer role: authentication is
-- performed on the normal platform connection before an accounting transaction
-- is opened, so the privileged writer never needs password hashes or user rows.
GRANT SELECT, INSERT, UPDATE, DELETE ON accounting.invoices TO accounting_app;
GRANT SELECT ON accounting.invoices TO clinical_app, platform_app;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA platform FROM accounting_app;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA platform FROM accounting_app;
