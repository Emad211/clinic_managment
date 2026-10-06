"""Dependency rules (docs/02 §3, docs/03 §11.5), checked statically on the AST."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PY_FILES = sorted(SRC.rglob("*.py")) + [ROOT / "start.py"]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported_modules(module: ast.Module) -> set[str]:
    out = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add("." * node.level + node.module)
    return out


def code_strings(module: ast.Module) -> list[str]:
    """String constants that are not docstrings."""
    docstrings = set()
    for node in ast.walk(module):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    return [n.value for n in ast.walk(module)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


def test_only_two_modules_open_sqlite():
    allowed = {"src/adapters/accounting/bridge.py", "src/adapters/sqlite/core.py"}
    offenders = []
    for path in PY_FILES:
        for node in ast.walk(tree(path)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "connect" and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "sqlite3" and rel(path) not in allowed):
                offenders.append(f"{rel(path)}:{node.lineno}")
    assert offenders == []


def test_read_only_uri_lives_only_in_the_bridge():
    for path in PY_FILES:
        if rel(path) == "src/adapters/accounting/bridge.py":
            continue
        assert not any("mode=ro" in s for s in code_strings(tree(path))), rel(path)


def test_no_imports_from_sibling_apps():
    for path in PY_FILES:
        for mod in imported_modules(tree(path)):
            head = mod.lstrip(".").split(".")[0]
            assert head not in {"webapp", "specialist_clinic"}, f"{rel(path)} imports {mod}"
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"sys\.path\.(insert|append)\([^)]*(webapp|specialist_clinic)", text), rel(path)


def test_forbidden_accounting_tricks_absent():
    pattern = re.compile(r"immutable\s*=|nolock\s*=|\bATTACH\b|journal_mode\s*=\s*WAL|wal_checkpoint", re.I)
    for path in (SRC / "adapters" / "accounting").rglob("*.py"):
        module = tree(path)
        for s in code_strings(module):
            assert not pattern.search(s), f"{rel(path)}: {s!r}"
        assert "shutil" not in imported_modules(module), rel(path)


def test_accounting_adapter_used_only_by_services_sync_and_wiring():
    allowed_prefixes = ("src/adapters/accounting/", "src/services/", "src/sync/")
    allowed_files = {"src/app.py"}
    for path in PY_FILES:
        r = rel(path)
        if r.startswith(allowed_prefixes) or r in allowed_files:
            continue
        for mod in imported_modules(tree(path)):
            assert "adapters.accounting" not in mod, f"{r} imports {mod}"


def test_domain_is_pure():
    banned = {"flask", "sqlite3", "werkzeug"}
    for path in (SRC / "domain").rglob("*.py"):
        module = tree(path)
        for mod in imported_modules(module):
            assert mod.lstrip(".").split(".")[0] not in banned, f"{rel(path)} imports {mod}"
            assert "iran_time" not in mod and "adapters" not in mod, f"{rel(path)} imports {mod}"
        for node in ast.walk(module):
            if (isinstance(node, ast.Attribute) and node.attr in {"now", "today", "utcnow", "time", "monotonic"}
                    and isinstance(node.value, ast.Name) and node.value.id in {"datetime", "date", "time"}):
                raise AssertionError(f"{rel(path)}:{node.lineno} reads the clock; inject time instead")


SQL = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|PRAGMA|BEGIN|COMMIT|WITH|REPLACE)\s", re.I)


def test_sql_only_in_adapters():
    for path in PY_FILES:
        if rel(path).startswith("src/adapters/"):
            continue
        for s in code_strings(tree(path)):
            assert not SQL.match(s), f"{rel(path)} contains SQL: {s[:60]!r}"
