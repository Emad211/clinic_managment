-- Preserve the source SQLite catalogue type without weakening operational enums.
ALTER TABLE accounting.services
    ADD COLUMN IF NOT EXISTS legacy_service_type TEXT;

ALTER TABLE accounting.services
    DROP CONSTRAINT IF EXISTS chk_services_legacy_type_format;
ALTER TABLE accounting.services
    ADD CONSTRAINT chk_services_legacy_type_format
    CHECK (
        legacy_service_type IS NULL
        OR legacy_service_type IN ('custom', 'medicine')
    ) NOT VALID;

COMMENT ON COLUMN accounting.services.legacy_service_type IS
    'Literal custom/medicine type from the legacy SQLite services catalogue.';
