from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from accounting_factory import FIXTURES, build_accounting_db  # noqa: E402
from src.adapters.accounting import bridge  # noqa: E402


def _digest_fixtures() -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(FIXTURES.iterdir()) if p.is_file()}


@pytest.fixture(scope="session", autouse=True)
def accounting_path_guard(tmp_path_factory):
    """docs/03 §11.2: tests may open only temp copies or synthetic DBs.

    The perf test may additionally open the local copy named by PEYGIRI_PERF_DB.
    Fixture files must be byte-identical at the end of the session.
    """
    allowed = [tmp_path_factory.getbasetemp().resolve()]
    perf = os.environ.get("PEYGIRI_PERF_DB")
    perf_path = Path(perf).resolve() if perf else None

    def guard(path: Path) -> None:
        if perf_path is not None and path == perf_path:
            return
        if not any(path.is_relative_to(root) for root in allowed):
            raise AssertionError(f"test tried to open a non-temporary accounting DB: {path}")

    before = _digest_fixtures()
    bridge.set_path_guard(guard)
    yield
    bridge.set_path_guard(None)
    assert _digest_fixtures() == before, "a test modified files under tests/fixtures"


@pytest.fixture
def acc_db(tmp_path) -> Path:
    # Persian name with a space, like the real deployment folders.
    return build_accounting_db(tmp_path / "حسابداری آزمون" / "clinic_new.db")
