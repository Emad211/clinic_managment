from __future__ import annotations

from pathlib import Path


path = Path(__file__).with_name("finalize_a13.py")
text = path.read_text(encoding="utf-8")

replacements = (
    (
        'if "CREATE TABLE IF NOT EXISTS clinical_rule_review_events" not in schema.read_text(encoding="utf-8"):\n'
        '    schema.write_text(schema.read_text(encoding="utf-8").rstrip() + schema_block + "\\n", encoding="utf-8")\n',
        'if "CREATE TABLE IF NOT EXISTS clinical_rule_review_events" not in schema.read_text(encoding="utf-8"):\n'
        '    schema.write_text(\n'
        '        schema.read_text(encoding="utf-8").rstrip()\n'
        '        + "\\n\\n"\n'
        '        + schema_block.strip()\n'
        '        + "\\n",\n'
        '        encoding="utf-8",\n'
        '    )\n',
    ),
    (
        '        elif action == "compare":\n'
        "''',\n"
        ')\n\n'
        'template = SPECIALIST / "src/templates/manager/clinical_engine.html"',
        "''',\n"
        ')\n\n'
        'template = SPECIALIST / "src/templates/manager/clinical_engine.html"',
    ),
    (
        '            note="reviewed",\n'
        '        )\n'
        "''',\n"
        ')\n\n'
        'write(\n'
        '    SPECIALIST / "tests/test_clinical_rule_review_governance_a13.py",',
        '            note="reviewed",\n'
        "''',\n"
        ')\n\n'
        'write(\n'
        '    SPECIALIST / "tests/test_clinical_rule_review_governance_a13.py",',
    ),
    (
        '                prior = db.execute(\n'
        '                    """SELECT id FROM clinical_rule_review_events\n'
        '                       WHERE ruleset_id=? AND rule_version_id=? AND role=?\n'
        '                       ORDER BY id DESC LIMIT 1""",\n'
        '                    (int(ruleset_id), rule_version_id, normalized_role),\n'
        '                ).fetchone()\n'
        '                identity = {\n',
        '                prior = db.execute(\n'
        '                    """SELECT * FROM clinical_rule_review_events\n'
        '                       WHERE ruleset_id=? AND rule_version_id=? AND role=?\n'
        '                       ORDER BY id DESC LIMIT 1""",\n'
        '                    (int(ruleset_id), rule_version_id, normalized_role),\n'
        '                ).fetchone()\n'
        '                if prior and all((\n'
        '                    str(prior["decision"]) == normalized_decisions[rule_code],\n'
        '                    str(prior["ruleset_content_hash"]) == str(ruleset["content_hash"]),\n'
        '                    str(prior["rule_content_hash"]) == str(member["content_hash"]),\n'
        '                    str(prior["package_hash"]) == package_digest,\n'
        '                    str(prior["case_bundle_hash"]) == case_digest,\n'
        '                    str(prior["reviewer_username"]) == username,\n'
        '                    str(prior["reviewer_display_name"]) == display_name,\n'
        '                    str(prior["note"]) == review_note,\n'
        '                )):\n'
        '                    continue\n'
        '                identity = {\n',
    ),
)

for old, new in replacements:
    if old in text:
        text = text.replace(old, new, 1)
        continue
    if new in text:
        continue
    raise RuntimeError(f"A13 generator repair anchor missing: {old[:120]!r}")

path.write_text(text, encoding="utf-8")
print("A13 generator repaired")
