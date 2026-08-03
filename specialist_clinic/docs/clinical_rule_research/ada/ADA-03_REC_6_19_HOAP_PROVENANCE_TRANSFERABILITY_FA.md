# ADA-03 — provenance و قابلیت انتقال HOAP

## یافتهٔ اصلی

HOAP یک guideline/algorithm داخلی Kaiser Permanente است که با مشارکت متخصصان و Delphi ساخته و در کتابخانهٔ داخلی KPNC منتشر شد. trial تصادفی، اجرای فعال آن توسط pharmacist expert را در برابر usual care پس از passive dissemination سنجید.

بنابراین trial دو موضوع را از هم جدا نمی‌کند:

1. اعتبار علمی تک‌تک threshold و actionهای HOAP؛
2. اثر یک workflow فعال، متخصص‌محور و integrated برای اجرای آن.

## Corrigendum v0.9.1: تفکیک trial documentation از internal guideline

مقالهٔ JAMA صراحتاً Trial Protocol و Statistical Analysis Plan را در `Supplement 1` قرار داده است. بنابراین عبارت کلی «هیچ protocol/SAP در دسترس نیست» صحیح نیست.

اما وجود Trial Protocol/SAP به معنی دسترسی یا اعتبارسنجی خود HOAP guideline نیست. این دو artifact باید مستقل نگه داشته شوند:

### Artifact A — Trial protocol/SAP

- در Supplement 1 مقاله قرار دارد؛
- public registration در ClinicalTrials.gov بعد از primary completion منتشر شده است؛
- تاریخ، امضا و نسخهٔ Supplement 1 نسبت به randomization هنوز به‌صورت مستقل ممیزی نشده است؛
- در نتیجه، prespecification عمومی و زمان‌دار هنوز `PARTIAL / HOLD` است.

### Artifact B — Internal HOAP guideline/algorithm

موارد زیر همچنان به دست نیامده یا تأیید نشده‌اند:

- نسخهٔ frozen و versioned guideline؛
- search strategy کامل؛
- evidence tables و clause-level evidence mapping؛
- Delphi rounds، response rate و consensus thresholds؛
- grading هر recommendation؛
- change history و governance داخلی؛
- حقوق ترجمه، adaptation و software encoding؛
- external validation خارج از KPNC.

## comparator و estimand واقعی trial

usual-care arm نیز پس از passive dissemination به HOAP دسترسی داشت. بنابراین contrast اصلی trial بیشتر این است:

`active expert-pharmacist implementation` در برابر `passive availability / usual care`

نه:

`valid HOAP algorithm` در برابر `no algorithm`.

به همین دلیل نمی‌توان کل اثر trial را به صحت مستقل thresholdها و actionهای داخلی HOAP نسبت داد.

## outcome و directness

Primary outcome یک process outcome بود: قرارگرفتن بیمار روی safer regimen در شش ماه. severe hypoglycemia primary outcome نبود و trial برای اثبات کاهش این رخداد به‌عنوان outcome اصلی قدرت کافی نداشت.

مقاله همچنین نشان می‌دهد که حتی در workflow ساختاریافته:

- برخی بیماران به‌دلیل symptomatic hyperglycemia، ترجیح بیمار یا داوری ایمنی قابل deprescribe نبودند؛
- تصمیم‌ها به individualization و shared decision-making نیاز داشتند؛
- intervention توسط pharmacist متخصص در یک integrated delivery system اجرا شد.

## موانع انتقال به مطب تخصصی

- ساختار KPNC با درمانگاه ایران هم‌ارز نیست؛
- availability و هزینهٔ pharmacist، CGM، glucagon و follow-up متفاوت است؛
- اتصال داده، medication reconciliation و referral pathway نیازمند local computability assessment است؛
- حقوق reuse/software adaptation روشن نیست؛
- actionهای دارویی بدون clinician review مجاز نیستند.

## نتیجهٔ مجاز

HOAP از این فرضیه حمایت می‌کند که یک proactive pharmacist/clinician-owned workflow می‌تواند safer prescribing process را تغییر دهد و ارزش shadow evaluation دارد.

نقش شواهدی مجاز:

`PROCESS_WORKFLOW_EVIDENCE_ONLY`

## نتیجهٔ غیرمجاز

- کپی HOAP به‌عنوان Rule Library؛
- بازسازی یا حدس thresholdهای غیرعمومی؛
- انتقال actionها بدون بازسازی مستقل شواهد؛
- نسبت‌دادن کل اثر trial به صحت الگوریتم؛
- فرض قابلیت اجرا در ایران؛
- استفاده، ترجمه یا software encoding بدون permission؛
- کاهش/قطع/تعویض خودکار دارو.

## Gate

`TRIAL_PROTOCOL_SAP_LOCATED + PUBLIC_PRESPECIFICATION_DATING_HOLD + INTERNAL_GUIDELINE_ACCESS_HOLD + METHOD_APPRAISAL_HOLD + LICENSING_HOLD`

- Rule Candidate = 0
- Accepted Rule = 0
- Runtime change = 0
- Clinical activation = BLOCKED
