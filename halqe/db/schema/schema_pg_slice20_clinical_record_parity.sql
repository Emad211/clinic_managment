-- ============================================================================
-- Clinical patient-record parity hardening (specialist_clinic -> halqe)
--
-- The underlying tables were translated in slice2.  This slice adds the
-- validation/index contracts required by the executable record editor without
-- rewriting or rejecting historical rows.  CHECK constraints are NOT VALID:
-- they enforce every new/updated row immediately while allowing a future ETL
-- cleanup to validate legacy data explicitly.
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'clinical.clinical_notes'::regclass
          AND conname = 'chk_clinical_notes_kind'
    ) THEN
        ALTER TABLE clinical.clinical_notes
            ADD CONSTRAINT chk_clinical_notes_kind
            CHECK (kind IN ('symptom','exam','lifestyle','general')) NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'clinical.clinical_notes'::regclass
          AND conname = 'chk_clinical_notes_body_not_blank'
    ) THEN
        ALTER TABLE clinical.clinical_notes
            ADD CONSTRAINT chk_clinical_notes_body_not_blank
            CHECK (body IS NULL OR btrim(body) <> '') NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'clinical.surgery_history'::regclass
          AND conname = 'chk_surgery_history_title_not_blank'
    ) THEN
        ALTER TABLE clinical.surgery_history
            ADD CONSTRAINT chk_surgery_history_title_not_blank
            CHECK (btrim(title) <> '') NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'clinical.medical_history'::regclass
          AND conname = 'chk_medical_history_title_not_blank'
    ) THEN
        ALTER TABLE clinical.medical_history
            ADD CONSTRAINT chk_medical_history_title_not_blank
            CHECK (btrim(title) <> '') NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'clinical.flag_catalog'::regclass
          AND conname = 'chk_flag_catalog_record_section'
    ) THEN
        ALTER TABLE clinical.flag_catalog
            ADD CONSTRAINT chk_flag_catalog_record_section
            CHECK (
                record_section IS NULL OR
                record_section IN ('lifestyle','exam','disease','general')
            ) NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'clinical.medication_events'::regclass
          AND conname = 'chk_medication_events_type'
    ) THEN
        ALTER TABLE clinical.medication_events
            ADD CONSTRAINT chk_medication_events_type
            CHECK (event_type IN ('start','stop','dose_change')) NOT VALID;
    END IF;
END
$$;

-- Backfill the record sections exactly as specialist_clinic::_seed_flag_sections.
UPDATE clinical.flag_catalog
SET record_section = CASE
    WHEN flag_key = 'metabolic_surgery' THEN 'disease'
    WHEN category IN ('cardiac','renal','hepatic','risk','repro') THEN 'disease'
    WHEN category = 'lifestyle' THEN 'lifestyle'
    WHEN category = 'exam' THEN 'exam'
    ELSE 'general'
END
WHERE record_section IS NULL;

CREATE INDEX IF NOT EXISTS idx_record_surgery_tenant_patient
    ON clinical.surgery_history (tenant_id, patient_link_id, performed_on DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_record_history_tenant_patient
    ON clinical.medical_history (tenant_id, patient_link_id, since DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_record_notes_tenant_patient
    ON clinical.clinical_notes (tenant_id, patient_link_id, kind, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_record_flags_tenant_patient
    ON clinical.patient_flags (tenant_id, patient_link_id, flag_key);
CREATE INDEX IF NOT EXISTS idx_record_labs_tenant_patient
    ON clinical.lab_results (tenant_id, patient_link_id, taken_at DESC);
CREATE INDEX IF NOT EXISTS idx_record_medevents_tenant_patient
    ON clinical.medication_events (tenant_id, patient_link_id, event_date, id);
CREATE INDEX IF NOT EXISTS idx_record_drug_catalog_tenant_name
    ON clinical.drug_catalog (tenant_id, generic_fa);
CREATE INDEX IF NOT EXISTS idx_record_condition_labs_tenant_condition
    ON clinical.condition_lab_tests (tenant_id, condition_code, display_order);

-- Tables pre-date slice5, so they already have RLS.  Repeat grants defensively
-- because schema files may be applied to a partially-provisioned database.
GRANT SELECT, INSERT, UPDATE, DELETE ON
    clinical.surgery_history,
    clinical.medical_history,
    clinical.clinical_notes,
    clinical.patient_flags,
    clinical.patient_conditions,
    clinical.patient_medications,
    clinical.medication_events,
    clinical.lab_results
TO clinical_app, platform_app;

GRANT SELECT ON
    clinical.flag_catalog,
    clinical.drug_classes,
    clinical.drug_catalog,
    clinical.lab_test_catalog,
    clinical.condition_lab_tests,
    clinical.clinical_indicators
TO clinical_app, platform_app;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA clinical
TO clinical_app, platform_app;
