"""
ClinicalRouter — database router enforcing the accounting read-only boundary.

Rules:
  accounting models (app_label='accounting')
    → db_for_read: 'accounting_read'
    → db_for_write: RAISES PermissionError (physically read-only boundary)

  platform_core models (app_label='platform_core')
    → db_for_read/write: 'default'

  clinical models (app_label='clinical')
    → db_for_read/write: 'default'

  accounting_port has no models — only a Port function.

allow_migrate: only 'default' db gets migrations (but managed=False means
Django never actually migrates these tables; apply_schema does it).
"""


class ClinicalRouter:
    # -----------------------------------------------------------------------
    # Read routing
    # -----------------------------------------------------------------------
    def db_for_read(self, model, **hints):
        if model._meta.app_label == "accounting":
            return "accounting_read"
        if model._meta.app_label in ("clinical", "platform_core"):
            return "default"
        return None

    # -----------------------------------------------------------------------
    # Write routing — accounting writes are FORBIDDEN
    # -----------------------------------------------------------------------
    def db_for_write(self, model, **hints):
        if model._meta.app_label == "accounting":
            raise PermissionError(
                f"Writing to accounting model '{model.__name__}' is forbidden. "
                "The accounting schema is read-only from the clinical side. "
                "Use AccountingReadPort for read-only access."
            )
        if model._meta.app_label in ("clinical", "platform_core"):
            return "default"
        return None

    # -----------------------------------------------------------------------
    # Migration
    # -----------------------------------------------------------------------
    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # managed=False means Django never touches these tables anyway.
        # Route all migrations to 'default' to avoid errors with accounting_read.
        if db == "accounting_read":
            return False
        return True
