from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_all_user_facing_clock_fields_use_native_time_picker():
    expected_fields = {
        "src/templates/appointments/new.html": 'type="time" class="time-input" name="time"',
        "src/templates/followups/worklist.html": 'type="time" class="time-input" name="scheduled_time"',
        "src/templates/sms/campaigns.html": 'type="time" class="time-input" name="scheduled_time"',
        "src/templates/manager/engagement.html": 'type="time" class="time-input" name="quiet_start"',
    }

    for template, control in expected_fields.items():
        markup = _read(template)
        assert control in markup
        assert 'step="900"' in markup

    assert 'type="time" class="time-input" name="quiet_end"' in _read(
        "src/templates/manager/engagement.html"
    )


def test_persian_datepicker_dark_theme_covers_base_and_selected_days():
    css = _read("src/static/css/app.css")
    assert ".datepicker-day-view .table-days td span" in css
    assert ".datepicker-day-view .table-days td.selected span" in css
    assert "background:transparent!important;color:var(--text)!important" in css


def test_datepicker_hides_the_english_calendar_switch_button():
    shell_script = _read("src/static/js/shell-automation-v2.js")
    assert "calendarSwitch: { enabled: false }" in shell_script
