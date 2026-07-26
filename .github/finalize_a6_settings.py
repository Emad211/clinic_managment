from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A6 settings anchor missing in {relative}: {old[:220]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "specialist_clinic/src/api/manager.py",
    '''        repo.set_setting('mediana_timeout', str(min(max(request.form.get('mediana_timeout', type=int) or 45, 10), 120)))
        repo.set_setting('reminder_template', request.form.get('reminder_template', '').strip())
''',
    '''        repo.set_setting('mediana_timeout', str(min(max(request.form.get('mediana_timeout', type=int) or 45, 10), 120)))
        for provider_name in ('kavenegar', 'mediana'):
            field = f'sms_cost_per_part_{provider_name}_toman'
            raw = str(request.form.get(field) or '').strip()
            if not raw:
                repo.set_setting(field, '')
                continue
            try:
                amount = int(raw)
            except ValueError:
                amount = -1
            if amount < 0:
                flash('هزینه هر بخش پیامک باید عدد صحیح نامنفی باشد.', 'error')
                return redirect(url_for('manager.settings'))
            repo.set_setting(field, str(amount))
        repo.set_setting('reminder_template', request.form.get('reminder_template', '').strip())
''',
)
replace_once(
    "specialist_clinic/src/api/manager.py",
    '''        'mediana_timeout': repo.get_setting('mediana_timeout', '45'),
        'reminder_template': repo.get_setting('reminder_template',
''',
    '''        'mediana_timeout': repo.get_setting('mediana_timeout', '45'),
        'sms_cost_per_part_kavenegar_toman': repo.get_setting(
            'sms_cost_per_part_kavenegar_toman', ''
        ),
        'sms_cost_per_part_mediana_toman': repo.get_setting(
            'sms_cost_per_part_mediana_toman', ''
        ),
        'reminder_template': repo.get_setting('reminder_template',
''',
)

replace_once(
    "specialist_clinic/src/templates/manager/settings.html",
    '''    <!-- متنِ یادآوری -->
''',
    '''    <div class="card" style="margin-top:var(--s4);">
        <div class="section-title">
            <svg class="icon"><use href="#i-banknote"></use></svg>
            <span>هزینه مستقیم پیامک برای سنجش کمپین</span>
            <span class="section-sub">تومان برای هر بخش؛ صرفاً برآورد تنظیم‌شده</span>
        </div>
        <div class="alert-banner alert-info">
            این نرخ «هزینه واقعی گزارش‌شده توسط پنل» نیست. تا زمانی که نرخ معتبر وارد نشود، ROI کمپین عمداً نمایش داده نمی‌شود.
        </div>
        <div class="grid grid-2" style="margin-top:var(--s3);">
            <div class="fld">
                <label>کاوه‌نگار — تومان برای هر بخش</label>
                <input type="number" min="0" name="sms_cost_per_part_kavenegar_toman"
                       value="{{ data.sms_cost_per_part_kavenegar_toman }}"
                       placeholder="خالی = هزینه نامشخص">
            </div>
            <div class="fld">
                <label>مدیانا — تومان برای هر بخش</label>
                <input type="number" min="0" name="sms_cost_per_part_mediana_toman"
                       value="{{ data.sms_cost_per_part_mediana_toman }}"
                       placeholder="خالی = هزینه نامشخص">
            </div>
        </div>
        <div class="help">پیام فارسی تک‌بخشی تا ۷۰ نویسه و چندبخشی با ظرفیت ۶۷ نویسه برای هر بخش برآورد می‌شود؛ پیام لاتین به‌ترتیب ۱۶۰/۱۵۳.</div>
    </div>

    <!-- متنِ یادآوری -->
''',
)

Path(__file__).unlink()
