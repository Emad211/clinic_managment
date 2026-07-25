# سخت‌گیری عملیاتی و امنیتی موتور بالینی

## مجوزها

routeهای بالینی به permission پایدار وابسته‌اند، نه نام role. `manager` و `staff`
فقط default bundle هستند و eventهای append-only کاربرمحور می‌توانند هر permission را
GRANT یا REVOKE کنند.

```text
patient.view
patient.edit
clinical.data.record
clinical.reconcile
clinical.conflict.resolve
clinical.encounter.manage
clinical.decision.record
clinical.task.view
clinical.task.transition
clinical.outcome.record
rule.review.clinical
rule.review.technical
rule.activate
operational.health.view
security.grant.manage
```

خواندن overrideها در صورت خطای storage، fail-closed است. self-grant ممنوع است و
تغییر permission به actor، reason و optimistic concurrency نیاز دارد.

## CSRF و session

تمام mutationهای session/cookie-based در production به token معتبر نیاز دارند. token
بعد از login rotate می‌شود، با constant-time comparison بررسی می‌شود و به فرم‌های POST
server-side تزریق می‌شود. API اکستنشن که session ندارد فقط به‌طور صریح exempt است و
همچنان bearer token، origin allowlist و rate limit دارد.

Session:

```text
HttpOnly
SameSite=Lax
Secure در production
عمر ۸ ساعت
بدون refresh خودکار در هر request
```

## scheduler

هر tick ابتدا lease سراسری می‌گیرد. هر job علاوه بر lease دارای idempotency key و
fencing token است. release، row lease را حذف نمی‌کند تا token میان process restartها
همواره صعودی بماند. worker قدیمی پس از expiry یا takeover نمی‌تواند job را finish کند.

## backup و restore

backup فقط وقتی پذیرفته می‌شود که:

```text
SQLite integrity_check = ok
SHA-256 فایل محاسبه شود
size ثبت شود
manifest JSON به‌صورت اتمیک کنار فایل نوشته شود
```

restore ابتدا source و manifest را verify می‌کند، سپس staging copy را دوباره hash و
integrity-check می‌کند و فقط در پایان `os.replace` انجام می‌دهد.

## audit integrity

در activation یک checkpoint از تمام جدول‌های immutable حیاتی ساخته می‌شود. checkpoint
شامل فقط root hash، counts، max rowid و chain hash است و هیچ PHI برنمی‌گرداند. activation
seal به id/hash همان checkpoint متصل است. هر update/delete آفلاین روی تاریخچهٔ مهرشده،
`valid_seal` و در نتیجه نمایش خروجی بالینی را fail-closed می‌کند.

## health

```text
/health/live     process liveness
/health/ready    فقط ready/not_ready و بدون PHI
/health/details  جزئیات boolean با operational.health.view
```

Readiness شامل quick_check، schema، activation seal، audit checkpoint و worker stuck
check است.

## محدودیت‌ها

- permissionهای بیشتری باید به‌تدریج روی mutationهای عمومی پرونده اعمال شوند؛ routeهای
  safety-critical در این tranche اولویت دارند.
- checkpoint جدید پس از activation و سپس از scheduler دوره‌ای ساخته می‌شود؛ eventهای
  جدید پیش از checkpoint بعدی با triggerهای append-only محافظت می‌شوند.
- telemetry فقط component/error code/trace id نگه می‌دارد و نباید متن بالینی یا شناسهٔ
  بیمار را ثبت کند.
