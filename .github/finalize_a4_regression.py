from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "specialist_clinic/tests/test_operational_security_hardening.py"
text = path.read_text(encoding="utf-8")
old = '''        "worker",
        "revenue_scope",
    }
'''
new = '''        "worker",
        "revenue_scope",
        "finance_projection",
    }
'''
if new not in text:
    if old not in text:
        raise AssertionError("A4 health regression anchor missing")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
Path(__file__).unlink()
