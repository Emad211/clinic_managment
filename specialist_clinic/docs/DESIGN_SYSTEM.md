# Design System — کلینیک تخصصی (Dark · Data-Dense Dashboard)

نسخه‌ی بازطراحی‌شده با **ui-ux-pro-max**. این سند، منبع واحد طراحی برای همه‌ی صفحات است.
هنگام بازطراحی هر قالب، **فقط** از توکن‌ها/کلاس‌ها/آیکون‌های این سند استفاده کنید.

> سبک: **Data-Dense Dashboard** + **Dark Mode**. فشرده ولی خوانا، رنگ‌های وضعیت، حداقل تزئین.

---

## اصول (HARD RULES — رعایت اجباری)

1. **منطق را تغییر نده.** هیچ‌وقت `url_for(...)`، نام endpoint، نام فیلدهای فرم (`name="..."`)،
   متغیرهای Jinja، `id`هایی که جاوااسکریپت به آن‌ها وابسته است (مثل `id="revChart"`,
   `id="chart-{{vt}}"`, `#flags`, `#wallet`, `#vitals`, `#labs`)، یا ساختار `{% ... %}` را عوض نکن.
   فقط **markup ظاهری + class + آیکون + چینش** را بهبود بده.
2. **RTL/فارسی/جلالی دست‌نخورده:** همه‌چیز راست‌به‌چپ. فیلترهای `|fa_num`, `|jalali`,
   `|jalali_date` و `class="jdate"` روی ورودی‌های تاریخ باید حفظ شوند.
3. **حذف ایموجی به‌عنوان آیکون.** هر ایموجی ساختاری (🩺📊🗓️💊🧪💳🔔📣⚡🧬🚨➕… و `×` حذف)
   را با `<svg class="icon"><use href="#i-NAME"></use></svg>` جایگزین کن (لیست پایین).
   ایموجی داخل متن محاوره‌ای اگر بود می‌تواند بماند، ولی آیکون‌های UI نه.
4. **بدون hex خام در markup.** رنگ‌ها از توکن (`var(--...)`) یا کلاس‌های رنگ (`.c-ok` و…) بیایند.
   استایل‌های inline قدیمی با hex را به توکن/کلاس تبدیل کن.
5. **هر دکمه/لینک کلیک‌پذیر:** `cursor:pointer` (کلاس `.btn` خودش دارد)، حالت focus قابل‌مشاهده
   (به‌صورت سراسری هست)، و آیکون‌دار شدن CTAها.
6. **چارت‌ها:** رنگ‌ها از `window.CLINIC_THEME` بیایند (در base.html تعریف شده). تیک/گرید تیره.

---

## توکن‌ها (CSS variables — در `app.css`)

| گروه | متغیرها |
|------|---------|
| سطوح | `--bg` `--bg-elev` `--bg2`(inputs) `--panel`(card) `--panel2`(raised/hover) `--panel3` |
| خطوط | `--line` `--line-soft` `--line-strong` |
| متن | `--text` `--muted` `--faint` |
| برند/معنایی | `--primary`/`--primary2`/`--primary-soft` و `--ok`/`--warn`/`--danger`/`--info`/`--violet` (هرکدام `-fg` و `-soft`) |
| فاصله | `--s1..--s8` (4..32px) |
| شعاع | `--r-sm`(8) `--radius`(14) `--r-lg`(18) `--r-pill` |
| سایه/موشن | `--shadow` `--shadow-sm` `--shadow-lg` `--ring` · `--t-fast/--t/--t-slow` `--ease` |
| کنترل‌ها | `--control-sm`(36) `--control-md`(42) `--control-lg`(48) `--touch-target`(44) |
| آیکن‌ها | `--icon-sm-size`(14) `--icon-md-size`(16) `--icon-lg-size`(20) |

رنگ متن روی پس‌زمینه‌ی tinted از `-fg` استفاده کن (مثلاً `color:var(--ok-fg)`)، نه رنگ پایه.

---

## کامپوننت‌ها (کلاس‌های آماده)

- **چیدمان:** `.topbar` (h1 + اکشن‌ها)، `.crumb` (مسیر راهنما)، `.page-intro`، `.grid .grid-2/3/4/auto`.
- **کارت:** `.card`، `.card-soft`، `.section-title` (با `.section-sub`)، `.guide`/`.guide-grid`.
- **KPI:** `.card.kpi` → داخلش `.ic` (آیکون)، `.num`، `.label`. واریانت: `.kpi-ok/.kpi-warn/.kpi-violet/.kpi-info`.
- **جدول:** درون `.table-wrap` بپیچ (اسکرول افقی موبایل)؛ `thead th` چسبان، hover ردیف خودکار.
- **دکمه:** `.btn` + `.btn-ghost/.btn-ok/.btn-warn/.btn-danger/.btn-violet` + اندازه `.btn-sm/.btn-lg/.btn-block`.
  دکمه‌ی فقط‌آیکون: `.btn .btn-icon`. حذف ردیف (× قبلی): `<button class="btn btn-sm btn-danger btn-icon"><svg class="icon icon-sm"><use href="#i-trash"></use></svg></button>`.
- **فرم:** `.row`/`.field`، یا فیلد فشرده‌ی ستونی `.fld` (label کوچک + input). `.help` برای متن راهنما. `.req` برای ستاره‌ی الزامی.
- **بَج/چیپ:** `.badge` + `.badge-ok/warn/danger/info/violet/primary/muted`. `.chip`، `.dot .dot-ok/warn/danger`، `.legend`، `.tag-list`.
- **تحلیلی:** `.tiles`/`.tile` (با `.t-label/.t-val/.t-meta/.t-delta/.t-bar` و سطح `.lvl-ok/warn/danger/none`)، `.mini`، `.risk-meter > .mk`.
- **کنترل‌ها:** `.switch`(+`.switch-row`)، `.seg`(دکمه‌ها با `.active`)، `.ind-chip`(+`.off`).
- **وضعیت:** `.flash`(+`-success/-info`)، `.alert-banner`(+`.alert-warn`)، `.empty`(آیکون+متن)، `.empty-mini`، `.skeleton`، `.spinner`.
- **پوسته موبایل:** زیر `900px` سایدبار به drawer تبدیل می‌شود؛ فقط از `.mobile-shell-header` و `.mobile-nav-toggle` سراسری استفاده کنید و ناوبری موازی نسازید.
- **خطا:** خطاهای 404/500 با `errors/error.html` و `.error-state` نمایش داده می‌شوند؛ متن فنی یا stack trace وارد UI نشود.
- **لیست/قانون:** `.list-row`، `.scroll-y`، `.rule-card`/`.rule-head`/`.fgrid.c2/.c3`/`.rule-foot`.
- **یوتیلیتی:** `.flex .items-center .justify-between .gap-2/3 .wrap .ms-auto .w-full .text-sm/xs .nums .sr-only .divider(-dashed)` و رنگ متن `.c-ok/.c-warn/.c-danger/.c-info/.c-violet`.

### قرارداد اندازه و رفتار

- دکمه عادی `42px`، دکمه کوچک `36px` و دکمه بزرگ `48px` حداقل ارتفاع دارد.
- ورودی و `select` عادی `42px` حداقل ارتفاع دارند؛ `textarea` بر اساس محتوای خود رشد می‌کند.
- دکمه فقط‌آیکن باید مربع، دارای `aria-label` و هم‌اندازه گونه متنی خود باشد.
- در عرض موبایل، تمام کنترل‌های تعاملی حداقل `44px` سطح لمس دارند.
- فرم در زمان submit به‌صورت سراسری `aria-busy` می‌گیرد و submitter به حالت «در حال انجام…» می‌رود؛ loading موردی نسازید.
- `.table-wrap` در صورت نیاز به اسکرول افقی به‌صورت خودکار focusable و دارای برچسب دسترس‌پذیر می‌شود.
- label مجاور کنترل در `.fld`/`.field` به‌صورت سراسری با همان کنترل مرتبط می‌شود؛ در کد جدید همچنان `for`/`id` صریح ترجیح دارد.
- اندازه فقط با گونه‌های استاندارد تعیین می‌شود؛ `height` و `padding` موردی در قالب ممنوع است.
- `.btn-secondary` نام سازگار قدیمی و از نظر بصری معادل `.btn-ghost` است؛ در کد جدید از `.btn-ghost` استفاده شود.

---

## آیکون‌ها (اسپرایت SVG در `base.html`)

استفاده: `<svg class="icon"><use href="#i-NAME"></use></svg>` (اندازه‌ها: `.icon-sm`/`.icon-lg`).
رنگ از `currentColor` می‌آید؛ پس رنگ آیکون = رنگ متن والد.

`dashboard` `users` `calendar` `bell` `list-checks` `megaphone` `settings` `log-out` `user`
`activity`(برند/بالینی) `plus` `line-chart` `bar-chart` `wallet` `pill`(دارو) `flask`(آزمایش)
`alert`(هشدار/آلرژی) `trash` `x` `check` `save` `edit` `search` `filter` `phone`
`stethoscope`(بیماری) `heart` `syringe`(تزریق) `trending-up` `gift`(اعتبار) `coins`/`banknote`(پول)
`clipboard`(قواعد/پروتکل) `shield`(ایمنی) `zap`(ثبت سریع/Red Flag) `building`(ویزیت/حسابداری)
`sigma`(جمع کل) `key`(کاربران) `info` `chevron-left` `arrow-left` `download` `menu`

**نگاشت پیشنهادی ایموجی→آیکون:** 🩺→stethoscope/activity · 📊/📈→line-chart/bar-chart · 🗓️→calendar ·
💊→pill · 🧪→flask · 💳→wallet · 🔔→bell/list-checks · 📣→megaphone · ⚡→zap · 🧬→activity ·
🚨/⚠️→alert · ➕→plus · 💰→banknote · 🎁→gift · 🏥/🏥→building · 👤→user · 💾→save · Σ→sigma · ×→x/trash.

---

## نمونه‌الگوها

KPI:
```html
<div class="card kpi kpi-ok">
  <div class="ic"><svg class="icon"><use href="#i-users"></use></svg></div>
  <div class="num">{{ stats.patients|fa_num }}</div>
  <div class="label">بیماران مزمن</div>
</div>
```

دکمه‌ی CTA با آیکون:
```html
<a class="btn" href="{{ url_for('patients.enroll') }}"><svg class="icon"><use href="#i-plus"></use></svg> ثبت‌نام بیمار</a>
```

جدول:
```html
<div class="table-wrap"><table> … </table></div>
```

حالت خالی:
```html
<div class="empty"><svg class="icon"><use href="#i-users"></use></svg><div>بیماری ثبت نشده</div></div>
```
