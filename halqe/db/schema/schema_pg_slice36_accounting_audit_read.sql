-- ==========================================================================
-- Manager accounting-audit read port and query indexes.
--
-- platform_app powers the physically SELECT-only ``accounting_read`` alias.
-- Clinical code must not see accounting activity logs because descriptions and
-- before/after values can contain financial or demographic context.
-- ==========================================================================

GRANT SELECT ON accounting.activity_logs TO platform_app;
REVOKE ALL ON accounting.activity_logs FROM clinical_app;

CREATE INDEX IF NOT EXISTS idx_activity_logs_tenant_user_created
    ON accounting.activity_logs (tenant_id, user_id, created_at DESC)
    WHERE user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_activity_logs_tenant_invoice_created
    ON accounting.activity_logs (tenant_id, invoice_id, created_at DESC)
    WHERE invoice_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_activity_logs_tenant_patient_created
    ON accounting.activity_logs (tenant_id, patient_id, created_at DESC)
    WHERE patient_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_activity_logs_tenant_category_created
    ON accounting.activity_logs (tenant_id, action_category, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_activity_logs_tenant_action_created
    ON accounting.activity_logs (tenant_id, action_type, created_at DESC);
