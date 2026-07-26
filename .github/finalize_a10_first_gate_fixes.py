from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Expose task identity under both canonical Worklist names.
repo = ROOT / "specialist_clinic/src/adapters/sqlite/encounter_plan_commitment_repo.py"
text = repo.read_text(encoding="utf-8")
text = text.replace(
    "SELECT link.task_id AS id,commitment.patient_link_id,",
    "SELECT link.task_id AS id,link.task_id AS task_id,commitment.patient_link_id,",
    1,
)
repo.write_text(text, encoding="utf-8")

# The initial UI finalizer inserted before the first endblock (the title block). Remove
# that exact section and place the corrected document-scoped section before content endblock.
template = ROOT / "specialist_clinic/src/templates/doctor_queue/document_detail.html"
text = template.read_text(encoding="utf-8")
wrong = '''
{% if current.commitments %}
<div class="card">
  <div class="section-title"><svg class="icon"><use href="#i-list-checks"></use></svg> تعهدهای اجرایی نسخه امضاشده</div>
  {% for item in current.commitments %}
  <div class="list-row">
    <div><b>{{ item.instruction }}</b><div class="muted text-xs">{{ item.commitment_type }} · {{ item.fulfillment }}{% if item.assigned_to %} · {{ item.assigned_to }}{% endif %}</div></div>
    <span class="badge badge-info">{{ item.due_at|jalali }}</span>
  </div>
  {% endfor %}
  <div class="help">این مجموعه بخشی از سند امضاشده است. تغییر عملیاتی موعد، مسئول یا وضعیت فقط در Worklist و به‌صورت event ثبت می‌شود.</div>
</div>
{% endif %}
'''
text = text.replace(wrong, "", 1)
correct = '''
{% if document.commitments %}
<div class="card">
  <div class="section-title"><svg class="icon"><use href="#i-list-checks"></use></svg> تعهدهای اجرایی نسخه امضاشده</div>
  {% for item in document.commitments %}
  <div class="list-row">
    <div><b>{{ item.instruction }}</b><div class="muted text-xs">{{ item.commitment_type }} · {{ item.fulfillment }}{% if item.assigned_to %} · {{ item.assigned_to }}{% endif %}</div></div>
    <span class="badge badge-info">{{ item.due_at|jalali }}</span>
  </div>
  {% endfor %}
  <div class="help">این مجموعه بخشی از سند امضاشده است. تغییر عملیاتی موعد، مسئول یا وضعیت فقط در Worklist و به‌صورت event ثبت می‌شود.</div>
</div>
{% endif %}
'''
if correct.strip() not in text:
    marker = "{% endblock %}"
    head, sep, tail = text.rpartition(marker)
    if not sep:
        raise AssertionError("A10 corrected document endblock missing")
    text = head + correct + "\n" + sep + tail
template.write_text(text, encoding="utf-8")

# Static source guard uses pathlib.
test = ROOT / "specialist_clinic/tests/test_encounter_plan_commitments_a10.py"
text = test.read_text(encoding="utf-8")
if "from pathlib import Path\n" not in text:
    text = text.replace(
        "from datetime import timedelta\n",
        "from datetime import timedelta\nfrom pathlib import Path\n",
        1,
    )
test.write_text(text, encoding="utf-8")

Path(__file__).unlink()
