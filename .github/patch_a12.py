from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPECIALIST = ROOT / "specialist_clinic"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"A12 compatibility anchor missing in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


bundle_path = (
    SPECIALIST
    / "src/domain/clinical_engine/rule_artifacts/2026.1-draft.3/validation-cases.json"
)
bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
for case in bundle["cases"]:
    if case["case_id"] == "GC-GUARD-001":
        case["case_id"] = "GC-POS-001"
bundle_path.write_text(
    json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

ui_test = SPECIALIST / "tests/test_clinical_engine_v2_manager_ui.py"
replace_once(
    ui_test,
    '''        ruleset_id = package["id"]

    incomplete = client.post(
''',
    '''        ruleset_id = package["id"]
        rule_codes = [item["rule_code"] for item in package["members"]]
        rule_count = len(rule_codes)

    incomplete = client.post(
''',
)
replace_once(
    ui_test,
    '''        data={"ruleset_id": ruleset_id, "reviewer": "doctor", "note": "reviewed",
              "attested_rule": ["T2-REDFLAG-BP", "T2-SAFE-MET-STOP"]},
''',
    '''        data={"ruleset_id": ruleset_id, "reviewer": "doctor", "note": "reviewed",
              "attested_rule": rule_codes},
''',
)
replace_once(
    ui_test,
    '''    assert "هر 2 قاعده تأیید" in html
''',
    '''    assert f"هر {rule_count} قاعده تأیید" in html
''',
)

print("A12 compatibility anchors updated")
