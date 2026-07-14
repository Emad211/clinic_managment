-- ============================================================================
-- Accounting administration invariants.
--
-- The operational migration originally consumed these tables read-only. The
-- manager configuration surface now writes them, so natural-key uniqueness and
-- non-negative price contracts must be enforced by PostgreSQL as well as the API.
-- Existing rows are left intact; duplicate exclusions are collapsed before the
-- unique constraint is created.
-- ============================================================================

DELETE FROM accounting.insurance_nursing_exclusions duplicate
USING accounting.insurance_nursing_exclusions keeper
WHERE duplicate.tenant_id = keeper.tenant_id
  AND duplicate.insurance_type = keeper.insurance_type
  AND duplicate.nursing_service_id = keeper.nursing_service_id
  AND duplicate.id > keeper.id;

CREATE UNIQUE INDEX IF NOT EXISTS uq_insurance_nursing_exclusion_natural
    ON accounting.insurance_nursing_exclusions
       (tenant_id, insurance_type, nursing_service_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'accounting.visit_tariffs'::regclass
          AND conname = 'chk_visit_tariffs_prices_nonnegative'
    ) THEN
        ALTER TABLE accounting.visit_tariffs
            ADD CONSTRAINT chk_visit_tariffs_prices_nonnegative
            CHECK (tariff_price >= 0 AND nursing_tariff >= 0) NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'accounting.nursing_services'::regclass
          AND conname = 'chk_nursing_services_price_nonnegative'
    ) THEN
        ALTER TABLE accounting.nursing_services
            ADD CONSTRAINT chk_nursing_services_price_nonnegative
            CHECK (unit_price >= 0) NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'accounting.procedure_tariffs'::regclass
          AND conname = 'chk_procedure_tariffs_price_nonnegative'
    ) THEN
        ALTER TABLE accounting.procedure_tariffs
            ADD CONSTRAINT chk_procedure_tariffs_price_nonnegative
            CHECK (unit_price >= 0) NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'accounting.consumable_tariffs'::regclass
          AND conname = 'chk_consumable_tariffs_price_nonnegative'
    ) THEN
        ALTER TABLE accounting.consumable_tariffs
            ADD CONSTRAINT chk_consumable_tariffs_price_nonnegative
            CHECK (default_price >= 0) NOT VALID;
    END IF;
END
$$;
