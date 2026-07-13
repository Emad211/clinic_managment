-- ==========================================================================
-- Procedure financial snapshots.
--
-- ``procedures.price`` remains the recorded/raw service price.  The migrated
-- accounting engine freezes the patient's liability and insurer contribution
-- at creation time so later tariff changes cannot reinterpret a closed period.
-- Existing rows remain legacy: NULL patient/insurance amounts fall back to raw
-- price only in read projections, and their invoice pricing_version prevents
-- the new close path from mutating them.
-- ==========================================================================

ALTER TABLE accounting.procedures
    ADD COLUMN IF NOT EXISTS patient_amount NUMERIC(14,0),
    ADD COLUMN IF NOT EXISTS insurance_amount NUMERIC(14,0),
    ADD COLUMN IF NOT EXISTS covered_by_insurance BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE accounting.procedures
    DROP CONSTRAINT IF EXISTS chk_procedures_patient_amount_nonnegative;
ALTER TABLE accounting.procedures
    ADD CONSTRAINT chk_procedures_patient_amount_nonnegative
        CHECK (patient_amount IS NULL OR patient_amount >= 0);

ALTER TABLE accounting.procedures
    DROP CONSTRAINT IF EXISTS chk_procedures_insurance_amount_nonnegative;
ALTER TABLE accounting.procedures
    ADD CONSTRAINT chk_procedures_insurance_amount_nonnegative
        CHECK (insurance_amount IS NULL OR insurance_amount >= 0);

COMMENT ON COLUMN accounting.procedures.patient_amount IS
    'Frozen patient liability in integer Toman; NULL means legacy/unmigrated row.';
COMMENT ON COLUMN accounting.procedures.insurance_amount IS
    'Frozen insurer contribution in integer Toman; NULL means legacy/unmigrated row.';
COMMENT ON COLUMN accounting.procedures.covered_by_insurance IS
    'True only when the migrated pricing engine explicitly covered this procedure.';
