from accounting_ops._import_common_core import *  # noqa: F401,F403


class SourceDatabaseError(AccountingImportError):
    """Raised when a legacy SQLite snapshot cannot be trusted or read."""
