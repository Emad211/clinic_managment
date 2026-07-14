-- ============================================================================
-- Target snapshot fingerprints for specialist record reconciliation.
--
-- `payload_sha256` proves what transformed source row was processed.  The
-- columns below independently fingerprint the actual target values that existed
-- immediately after insert/reuse.  A verifier can therefore detect silent target
-- mutation even when the ledger pointer and primary key still exist.
--
-- Existing rehearsal ledgers remain readable: an empty column array plus NULL
-- digest denotes a pre-fingerprint entry and is rejected by the release verifier
-- until the rehearsal is repeated with a fresh source-id.
-- ============================================================================

ALTER TABLE clinical.record_import_ledger
    ADD COLUMN IF NOT EXISTS target_payload_columns TEXT[]
        NOT NULL DEFAULT ARRAY[]::TEXT[],
    ADD COLUMN IF NOT EXISTS target_payload_sha256 TEXT;

ALTER TABLE clinical.record_import_ledger
    DROP CONSTRAINT IF EXISTS chk_record_import_target_snapshot_pair;
ALTER TABLE clinical.record_import_ledger
    ADD CONSTRAINT chk_record_import_target_snapshot_pair
    CHECK (
        (
            target_payload_sha256 IS NULL
            AND cardinality(target_payload_columns) = 0
        )
        OR
        (
            target_payload_sha256 ~ '^[0-9a-f]{64}$'
            AND cardinality(target_payload_columns) > 0
        )
    );

COMMENT ON COLUMN clinical.record_import_ledger.target_payload_columns IS
    'Sorted target columns included in the post-insert/reuse snapshot digest.';
COMMENT ON COLUMN clinical.record_import_ledger.target_payload_sha256 IS
    'SHA-256 of the canonical actual target values for target_payload_columns.';
