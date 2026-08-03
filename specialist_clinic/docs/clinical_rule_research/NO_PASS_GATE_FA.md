# گیت اجباری NO_PASS_WITHOUT_VERIFICATION

این سند برای تمام پژوهش‌ها، Recommendationها، Evidence Dossierها و Rule Candidateهای موتور بالینی الزام‌آور است.

## اصل حاکم

هیچ عدد، threshold، فاصلهٔ پایش، تعریف رخداد، منع مصرف، توصیهٔ درمانی، هشدار، Care Gap یا Rule صرفاً به علت وجود در گایدلاین، مقاله، کد قدیمی یا عرف بالینی عبور نمی‌کند.

## شروط عبور Recommendation به مرحلهٔ Evidence Dossier

- منبع مادر و نسخهٔ دقیق مشخص باشد؛
- Recommendation و locator رسمی ثبت شده باشد؛
- متن کامل بخش خوانده شده باشد؛
- Grade منبع بدون تحریف ثبت شده باشد؛
- بندهای دارای Grade متفاوت جدا شده باشند؛
- جمعیت، setting، استثناها و وابستگی‌ها روشن باشند؛
- وضعیت licensing ثبت شده باشد.

## شروط عبور Evidence Dossier به Rule Candidate

- citation chain و supplemental search تکمیل شده باشد؛
- تمام مقالات تعیین‌کننده با متن کامل استخراج شده باشند؛
- Abstract به‌تنهایی مبنای نتیجه نباشد؛
- design-specific Risk of Bias تکمیل شده باشد؛
- directness هر منبع مشخص باشد؛
- سود، زیان، subgroup و عدم قطعیت ثبت شده باشد؛
- گایدلاین‌های هم‌پوشان مقایسه شده باشند؛
- تعارض واقعی حل شده باشد؛
- Iranian Context فقط در نقش adaptation استفاده شده باشد؛
- licensing برای formalization روشن باشد؛
- Factهای لازم و کیفیت داده موجود باشند.

## شروط عبور Rule Candidate به DRAFT

- population و eligibility؛
- required/optional facts؛
- unit و conversion؛
- verification و source؛
- effective/recorded time؛
- freshness؛
- condition و threshold؛
- exception و contraindication؛
- missing/conflict behavior؛
- suppression؛
- output، owner، priority و SLA؛
- evidence provenance؛
- computability؛
- clinician ownership

باید دقیقاً formalize شده باشند.

## شروط عبور DRAFT به SILENT/PILOT/ACTIVE

- clinical content review؛
- technical review؛
- positive/negative/borderline/missing/conflict/historical/contraindication/suppression golden cases؛
- multimorbidity scenarios؛
- retrospective validation؛
- SILENT analysis؛
- adjudication تمام اختلاف‌های ایمنی؛
- alert-burden و workflow validation؛
- approval بالینی و فنی؛
- activation seal و rollback plan.

## توقف‌های اجباری

موارد زیر فوراً فرایند را متوقف می‌کنند:

- متن کامل تعیین‌کننده در دسترس نیست؛
- locator مبهم است؛
- Grade یا population نامشخص است؛
- دو منبع threshold یا action متعارض دارند؛
- مقالهٔ نگران‌کنندهٔ harm حل نشده است؛
- Fact لازم در پرونده وجود ندارد؛
- missing به false تبدیل می‌شود؛
- action دارویی یا ارجاع خودکار پیشنهاد شده است؛
- licensing نامشخص است؛
- validation یا approval ناقص است.

## قواعد ممنوع

- threshold averaging؛
- cherry-picking؛
- انتخاب منبع صرفاً به دلیل جدیدتر یا مشهورتر بودن؛
- تبدیل مثال زمانی به ساعت ثابت؛
- تبدیل outcome فرایندی به اثربخشی بالینی؛
- پنهان‌کردن تعارض؛
- grandfather کردن Rule قدیمی؛
- نسبت‌دادن دو ارزیاب انسانی مستقل به فرایند دوپاسی یک ارزیاب؛
- اجرای خودکار medication change، diagnosis، referral، order یا patient message.

## خروجی هنگام عدم قطعیت

خروجی مجاز یکی از این موارد است:

- `NEEDS_DATA`
- `NOT_APPLICABLE`
- `CONFLICT`
- `CLINICIAN_REVIEW`
- `EVIDENCE_INCOMPLETE`
- `LICENSING_HOLD`
- `CLINICAL_HOLD`
- `REJECTED`

عبور ساکت و حدس‌زدن ممنوع است.
