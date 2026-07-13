-- ==========================================================================
-- Accounting paid-only close gate (defence in depth).
--
-- The application service returns a friendly ``invoice_unpaid_items`` conflict,
-- but money safety must not depend solely on one HTTP path.  Any UPDATE that
-- transitions an accounting invoice to ``closed`` is rejected while at least
-- one visit/injection/procedure/consumable lacks a paid item-payment row.
-- ==========================================================================

CREATE OR REPLACE FUNCTION accounting.enforce_invoice_paid_before_close()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = accounting, pg_temp
AS $$
BEGIN
    IF NEW.status = 'closed' AND OLD.status IS DISTINCT FROM 'closed' THEN
        IF EXISTS (
            SELECT 1
            FROM (
                SELECT 'visit'::text AS item_type, v.id AS item_id
                FROM accounting.visits v
                WHERE v.tenant_id = NEW.tenant_id AND v.invoice_id = NEW.id

                UNION ALL

                SELECT 'injection'::text, i.id
                FROM accounting.injections i
                WHERE i.tenant_id = NEW.tenant_id AND i.invoice_id = NEW.id

                UNION ALL

                SELECT 'procedure'::text, p.id
                FROM accounting.procedures p
                WHERE p.tenant_id = NEW.tenant_id AND p.invoice_id = NEW.id

                UNION ALL

                SELECT 'consumable'::text, c.id
                FROM accounting.consumables_ledger c
                WHERE c.tenant_id = NEW.tenant_id AND c.invoice_id = NEW.id
            ) item
            LEFT JOIN accounting.invoice_item_payments pay
              ON pay.tenant_id = NEW.tenant_id
             AND pay.invoice_id = NEW.id
             AND pay.item_type = item.item_type
             AND pay.item_id = item.item_id
            WHERE COALESCE(pay.is_paid, FALSE) = FALSE
        ) THEN
            RAISE EXCEPTION 'invoice_has_unpaid_items'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_invoice_paid_before_close ON accounting.invoices;
CREATE TRIGGER trg_invoice_paid_before_close
BEFORE UPDATE OF status ON accounting.invoices
FOR EACH ROW
EXECUTE FUNCTION accounting.enforce_invoice_paid_before_close();

REVOKE ALL ON FUNCTION accounting.enforce_invoice_paid_before_close() FROM PUBLIC;

-- The trigger invokes the function internally; application roles do not need
-- direct EXECUTE privileges.
