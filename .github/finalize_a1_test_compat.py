from pathlib import Path

path = Path(__file__).resolve().parents[1] / "specialist_clinic/tests/test_operational_security_hardening.py"
text = path.read_text(encoding="utf-8")
old = '''        "audit",
        "worker",
    }
'''
new = '''        "audit",
        "worker",
        "revenue_scope",
    }
'''
if new not in text:
    if old not in text:
        raise AssertionError("health contract test anchor missing")
    text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
Path(__file__).unlink()
