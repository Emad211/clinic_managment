"""
Management command: seed_clinical_rules

Loads the full clinical rule catalog from specialist_clinic's
clinical_rules_seed.py into clinical.clinical_rules — FAITHFULLY.

Same rule_code / condition_code / trigger_json / message / section /
severity as the source of truth. Idempotent: ON CONFLICT (tenant_id,
rule_code) DO NOTHING — so manager edits to existing rows are preserved.

Usage:
  python manage.py seed_clinical_rules
  python manage.py seed_clinical_rules --tenant-id 1
  python manage.py seed_clinical_rules --force-update  # UPDATE existing rows too
"""
import json
import os
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


def _import_rules():
    """Import RULES from specialist_clinic/src/adapters/sqlite/clinical_rules_seed.py."""
    seed_path = (
        Path(__file__).resolve().parent.parent.parent.parent.parent
        / "specialist_clinic"
        / "src"
        / "adapters"
        / "sqlite"
        / "clinical_rules_seed.py"
    )
    if not seed_path.exists():
        raise CommandError(
            f"clinical_rules_seed.py not found at expected path: {seed_path}\n"
            "Ensure the halqe/ directory sits next to specialist_clinic/."
        )
    import importlib.util
    spec = importlib.util.spec_from_file_location("clinical_rules_seed", seed_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.RULES, mod._condition_for


class Command(BaseCommand):
    help = (
        "Seed clinical.clinical_rules from specialist_clinic's clinical_rules_seed.py."
        " Idempotent (ON CONFLICT DO NOTHING by default)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant-id",
            type=int,
            default=1,
            help="Tenant ID to seed rules for (default: 1).",
        )
        parser.add_argument(
            "--force-update",
            action="store_true",
            default=False,
            help=(
                "If set, UPDATE existing rule rows (clobbers manager edits). "
                "Default: DO NOTHING on conflict — preserves manager edits."
            ),
        )

    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        force_update = options["force_update"]

        try:
            RULES, _condition_for = _import_rules()
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"Failed to import rule catalog: {exc}") from exc

        self.stdout.write(
            self.style.NOTICE(
                f"Seeding {len(RULES)} clinical rules into tenant={tenant_id} …"
            )
        )

        # Use psycopg directly (autocommit) so we can run the full batch
        # without Django ORM migration conflicts.
        import psycopg
        from django.conf import settings

        db_conf = settings.DATABASES["default"]

        def _build_conninfo(conf):
            parts = []
            for dk, pk in [("NAME", "dbname"), ("USER", "user"),
                           ("PASSWORD", "password"), ("HOST", "host"), ("PORT", "port")]:
                v = conf.get(dk)
                if v:
                    parts.append(f"{pk}='{str(v).replace(chr(39), chr(92)+chr(39))}'")
            return " ".join(parts)

        conninfo = _build_conninfo(db_conf)

        inserted = 0
        updated = 0
        skipped = 0

        with psycopg.connect(conninfo, autocommit=True) as conn:
            for r in RULES:
                condition_code = _condition_for(r)
                trigger = (
                    json.dumps(r["trigger"], ensure_ascii=False)
                    if r.get("trigger") is not None
                    else None
                )
                params = (
                    json.dumps(r["params"], ensure_ascii=False)
                    if r.get("params") is not None
                    else None
                )

                if force_update:
                    conn.execute(
                        """
                        INSERT INTO clinical.clinical_rules
                            (tenant_id, rule_code, title, category, condition_code,
                             trigger_json, human_if, recommendation, dosage_titration,
                             monitoring, contraindications, evidence_level,
                             action_type, action_params_json, severity, priority,
                             source_ref, is_active)
                        VALUES
                            (%(tid)s, %(rc)s, %(title)s, %(cat)s, %(cc)s,
                             %(trig)s::jsonb, %(hif)s, %(rec)s, %(dos)s,
                             %(mon)s, %(contra)s, %(ev)s,
                             %(act)s, %(aparams)s::jsonb, %(sev)s, %(pri)s,
                             %(src)s, TRUE)
                        ON CONFLICT (tenant_id, rule_code) DO UPDATE
                            SET title           = EXCLUDED.title,
                                category        = EXCLUDED.category,
                                condition_code  = EXCLUDED.condition_code,
                                trigger_json    = EXCLUDED.trigger_json,
                                human_if        = EXCLUDED.human_if,
                                recommendation  = EXCLUDED.recommendation,
                                dosage_titration= EXCLUDED.dosage_titration,
                                monitoring      = EXCLUDED.monitoring,
                                contraindications= EXCLUDED.contraindications,
                                evidence_level  = EXCLUDED.evidence_level,
                                action_type     = EXCLUDED.action_type,
                                action_params_json = EXCLUDED.action_params_json,
                                severity        = EXCLUDED.severity,
                                priority        = EXCLUDED.priority,
                                source_ref      = EXCLUDED.source_ref
                        """,
                        {
                            "tid": tenant_id,
                            "rc": r["code"],
                            "title": r["title"],
                            "cat": r["category"],
                            "cc": condition_code,
                            "trig": trigger,
                            "hif": r.get("human_if"),
                            "rec": r.get("rec"),
                            "dos": r.get("dosage_titration"),
                            "mon": r.get("monitoring"),
                            "contra": r.get("contraindications"),
                            "ev": r.get("evidence"),
                            "act": r.get("action", "educate"),
                            "aparams": params,
                            "sev": r.get("severity", "info"),
                            "pri": r.get("priority", 100),
                            "src": r.get("source"),
                        },
                    )
                    updated += 1
                else:
                    result = conn.execute(
                        """
                        INSERT INTO clinical.clinical_rules
                            (tenant_id, rule_code, title, category, condition_code,
                             trigger_json, human_if, recommendation, dosage_titration,
                             monitoring, contraindications, evidence_level,
                             action_type, action_params_json, severity, priority,
                             source_ref, is_active)
                        VALUES
                            (%(tid)s, %(rc)s, %(title)s, %(cat)s, %(cc)s,
                             %(trig)s::jsonb, %(hif)s, %(rec)s, %(dos)s,
                             %(mon)s, %(contra)s, %(ev)s,
                             %(act)s, %(aparams)s::jsonb, %(sev)s, %(pri)s,
                             %(src)s, TRUE)
                        ON CONFLICT (tenant_id, rule_code) DO NOTHING
                        """,
                        {
                            "tid": tenant_id,
                            "rc": r["code"],
                            "title": r["title"],
                            "cat": r["category"],
                            "cc": condition_code,
                            "trig": trigger,
                            "hif": r.get("human_if"),
                            "rec": r.get("rec"),
                            "dos": r.get("dosage_titration"),
                            "mon": r.get("monitoring"),
                            "contra": r.get("contraindications"),
                            "ev": r.get("evidence"),
                            "act": r.get("action", "educate"),
                            "aparams": params,
                            "sev": r.get("severity", "info"),
                            "pri": r.get("priority", 100),
                            "src": r.get("source"),
                        },
                    )
                    if result.rowcount > 0:
                        inserted += 1
                    else:
                        skipped += 1

        if force_update:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. {len(RULES)} rules upserted (force-update) "
                    f"for tenant={tenant_id}."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. {inserted} inserted, {skipped} already existed "
                    f"(skipped) for tenant={tenant_id}."
                )
            )
