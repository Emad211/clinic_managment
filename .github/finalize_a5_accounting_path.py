from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A5 app-config anchor missing in {relative}: {old[:180]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Flask defaults are always loaded; test/runtime overrides are applied afterward. This
# snapshots ACCOUNTING_DB_PATH per app instead of relying on mutable class state.
replace_once(
    "specialist_clinic/src/app.py",
    '''    if test_config is None:
        app.config.from_object(Config)
    else:
        app.config.from_mapping(test_config)
''',
    '''    app.config.from_object(Config)
    if test_config is not None:
        app.config.update(test_config)
''',
)

for relative in (
    "specialist_clinic/src/adapters/accounting_bridge.py",
    "specialist_clinic/src/adapters/specialist_accounting_revenue.py",
    "specialist_clinic/src/adapters/specialist_accounting_invoice_reader.py",
):
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if "from src.adapters.accounting_path import accounting_db_path" not in text:
        text = text.replace(
            "from src.config.settings import Config\n",
            "from src.adapters.accounting_path import accounting_db_path\n",
            1,
        )
    text = text.replace(
        "path = Config.ACCOUNTING_DB_PATH",
        "path = accounting_db_path()",
    )
    if "Config.ACCOUNTING_DB_PATH" in text:
        raise AssertionError(f"global accounting path remains in {relative}")
    path.write_text(text, encoding="utf-8")

Path(__file__).unlink()
