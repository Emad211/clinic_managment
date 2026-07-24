from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
template = root / "specialist_clinic/src/templates/patients/detail.html"
api = root / "specialist_clinic/src/api/patients.py"
analytics = root / "specialist_clinic/src/services/analytics_service.py"
test = root / "specialist_clinic/tests/test_parallel_clinical_logic_retired.py"

s = template.read_text(encoding="utf-8")
s = re.sub(
    r"\n\{% set lvlclass = .*?%\}\n\{% set lvlcolor = .*?%\}\n\{% set riskpos = .*?%\}\n",
    "\n",
    s,
    count=1,
)
status = re.search(
    r'<div class="patient-status-strip" aria-label="خلاصه وضعیت بیمار">.*?</div>\n\n    <aside',
    s,
    flags=re.S,
)
if not status:
    raise RuntimeError("patient status strip not found")
replacement = '''<div class="patient-status-strip" aria-label="خلاصهٔ اداری پرونده">
        <div class="patient-status-item">
            <span>پیگیری باز</span><strong>{{ followups|length|fa_num }}</strong>
        </div>
        <div class="patient-status-item">
            <span>موعد تجدید نسخه</span><strong>{{ refill_due|fa_num }}</strong>
        </div>
        <div class="patient-status-item">
            <span>نوبت ثبت‌شده</span><strong>{{ appt_summary.upcoming|length|fa_num }}</strong>
        </div>
        <div class="patient-status-item">
            <span>ویزیت ثبت‌شده</span><strong>{{ visits_count|fa_num }}</strong>
        </div>
    </div>

    <aside'''
s = s[: status.start()] + replacement + s[status.end() :]
s = s.replace(
    "به تفکیک بیماری · آخرین مقدار · روند · هدف",
    "به تفکیک بیماری · آخرین مقدار و تغییر عددی",
)
s = re.sub(
    r'''\n\s*<span class="badge \{\{ 'badge-danger' if d\.status=='danger'.*?</span>\n\s*<span class="badge \{\{ 'badge-danger' if d\.risk_level=='high'.*?</span>''',
    "",
    s,
    flags=re.S,
)
s = s.replace('<div class="vital-stat lvl-{{ i.level }}">', '<div class="vital-stat">')
s = re.sub(
    r'''<div class="vs-meta">\s*\{% if i\.target is not none %\}.*?\{% endif %\}\s*\{% if i\.delta is not none and i\.delta != 0 %\}.*?\{% endif %\}\s*</div>''',
    '''<div class="vs-meta">
                        {% if i.delta is not none and i.delta != 0 %}<span class="vs-delta">{% if i.delta > 0 %}▲{% else %}▼{% endif %}{{ (i.delta if i.delta>0 else 0-i.delta)|fa_num }} نسبت به ثبت قبل</span>{% endif %}
                        {% if i.last_date %}<span>{{ i.last_date }}</span>{% endif %}
                    </div>''',
    s,
    flags=re.S,
)
s = re.sub(
    r'''\n\s*\{% if risk\.behavior_notes %\}.*?\{% endif %\}\n''',
    "\n",
    s,
    count=1,
    flags=re.S,
)
s = re.sub(
    r'''\n\s*\{# ---- DOSE TOOLS.*?\{% endif %\}\n\n    \{# ---- CURRENT MEDICATIONS''',
    "\n\n    {# ---- CURRENT MEDICATIONS",
    s,
    count=1,
    flags=re.S,
)
s = re.sub(
    r'''\n\s*\{% if is_diabetic %\}\n\s*<div class="med-modal" data-modal="insulinModal".*?\n\s*\{% endif %\}\n''',
    "\n",
    s,
    count=1,
    flags=re.S,
)
s = re.sub(
    r'''\n\s*\{% for dg in dose_guidance %\}\n\s*<div class="med-modal" data-modal="doseModal-.*?\n\s*\{% endfor %\}\n''',
    "\n",
    s,
    count=1,
    flags=re.S,
)
s = re.sub(
    r'''<label>\{\{ i\.label \}\}\s*\{% if i\.target is not none %\}<span class="muted">\(هدف .*?\{% endif %\}\s*</label>''',
    '<label>{{ i.label }}</label>',
    s,
    flags=re.S,
)
s = s.replace('<div class="tile lvl-{{ i.level }}">', '<div class="tile">')
s = s.replace(
    '<div class="t-val" style="color:{{ lvlcolor.get(i.level,\'var(--text)\') }};">',
    '<div class="t-val">',
)
s = re.sub(
    r'''\{% if i\.delta is not none and i\.delta != 0 %\}\s*\{% set improved = .*?%\}\s*<div class="t-delta \{\{ .*?</div>\s*\{% endif %\}''',
    '''{% if i.delta is not none and i.delta != 0 %}
                    <div class="t-delta">{% if i.delta > 0 %}▲{% else %}▼{% endif %} {{ (i.delta if i.delta>0 else 0-i.delta)|fa_num }} <span class="muted" style="font-weight:400;">نسبت به ثبت قبل</span></div>
                {% endif %}''',
    s,
    flags=re.S,
)
s = re.sub(
    r'''<div class="t-meta">\s*\{% if i\.target is not none %\}.*?\{% endif %\}\s*\{% if i\.goal_low is not none and i\.goal_high is not none %\}.*?\{% endif %\}\s*· \{\{ i\.count\|fa_num \}\} ثبت\s*</div>''',
    '<div class="t-meta">{{ i.count|fa_num }} ثبت{% if i.last_date %} · آخرین ثبت {{ i.last_date }}{% endif %}</div>',
    s,
    flags=re.S,
)
s = re.sub(
    r'''\n\s*\{% if i\.bar_pct %\}<div class="t-bar">.*?</div>\{% endif %\}''',
    "",
    s,
    flags=re.S,
)
s = re.sub(r"^const targets\s*=.*?;\n", "", s, flags=re.M)
s = re.sub(
    r'''\n\s*if\(sel\.length===1 && series\[sel\[0\]\]\.target!=null\)\{.*?\}\s*\}\n\s*const TICK''',
    "\n        const TICK",
    s,
    count=1,
    flags=re.S,
)
s = s.replace(
    "            const good = j.improved===true, bad = j.improved===false;\n"
    "            const col = good?(TH.ok||'#4ade80'):(bad?(TH.danger||'#f87171'):(TH.tick||'#92a2c0'));\n",
    "            const col = TH.tick||'#92a2c0';\n",
)
s = s.replace(
    "<div class=\"mini\" style=\"flex:1;min-width:120px;\"><div class=\"m-num\" style=\"color:${col};\">${arrow} ${faDigit(Math.abs(j.delta))}</div><div class=\"m-lbl\">${good?'بهبود':(bad?'بدتر شدن':'تغییر')}</div></div>",
    "<div class=\"mini\" style=\"flex:1;min-width:120px;\"><div class=\"m-num\" style=\"color:${col};\">${arrow} ${faDigit(Math.abs(j.delta))}</div><div class=\"m-lbl\">تغییر عددی</div></div>",
)
s = re.sub(
    r'''\n/\* ===== insulin titration calculator.*?\n\}\)\(\);\n''',
    "\n",
    s,
    count=1,
    flags=re.S,
)
for token in (
    "insulinModal",
    "insBtn",
    "insTarget",
    "شروع انسولین پایه",
    "گام بعدی پیشنهادی",
    "بولوس پراندیال",
    "پیشنهاد دوزِ",
    "ریسک بالینی",
    "کنترل کلی",
    "series[sel[0]].target",
):
    if token in s:
        raise RuntimeError(f"retired clinical UI token remains: {token}")
template.write_text(s, encoding="utf-8")

a = api.read_text(encoding="utf-8")
a = a.replace(
    "from src.services.analytics_service import AnalyticsService, TARGETS",
    "from src.services.analytics_service import AnalyticsService",
)
a = a.replace("        targets=TARGETS,\n", "")
a = re.sub(
    r'''\n    # Meds tab \(Phase 3\):.*?\n    medication_events =''',
    '''\n    # Medications remain descriptive; dosing recommendations belong to governed v2 output.\n    drug_catalog = DrugCatalogRepository().all()\n    medication_events =''',
    a,
    count=1,
    flags=re.S,
)
a = a.replace("        is_diabetic=is_diabetic,\n", "")
a = a.replace("        dose_guidance=dose_guidance,\n", "")
if "dosage_guidance" in a or "TARGETS" in a:
    raise RuntimeError("legacy dose/target route wiring remains")
api.write_text(a, encoding="utf-8")

analytics_text = analytics.read_text(encoding="utf-8")
analytics_text = analytics_text.replace(
    "# Backward-compatible static targets (the patient detail page imports this).\n"
    "TARGETS = {'hba1c': 7.0, 'fbs': 130, 'bp_systolic': 130, 'bp_diastolic': 80}\n\n",
    "",
)
analytics.write_text(analytics_text, encoding="utf-8")

test.write_text(
    '''"""Regression guards for clinical interpretation outside governed v2 output."""\nfrom pathlib import Path\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef source(relative: str) -> str:\n    return (ROOT / "src" / relative).read_text(encoding="utf-8")\n\n\ndef test_patient_page_has_no_insulin_or_dose_recommendation_calculator():\n    page = source("templates/patients/detail.html")\n    route = source("api/patients.py")\n    for token in (\n        "insulinModal", "insBtn", "insTarget", "شروع انسولین پایه",\n        "گام بعدی پیشنهادی", "بولوس پراندیال", "پیشنهاد دوزِ",\n    ):\n        assert token not in page\n    assert "dosage_guidance" not in route\n    assert "TARGETS" not in route\n\n\ndef test_patient_trends_show_values_and_deltas_without_targets_or_risk_labels():\n    page = source("templates/patients/detail.html")\n    assert "ریسک بالینی" not in page\n    assert "کنترل کلی" not in page\n    assert "ریسک: {{ d.risk_label }}" not in page\n    assert "series[sel[0]].target" not in page\n    assert "FPG در محدودهٔ هدف" not in page\n    assert "تغییر عددی" in page\n''',
    encoding="utf-8",
)
