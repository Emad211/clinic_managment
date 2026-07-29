# ADA-03 — نقشهٔ اولیهٔ شواهد Recommendation 6.19

## وضعیت

- مطالعات غربال‌شده: 10
- استخراج متن کامل: 7
- ارزیابی مقدماتی Risk of Bias: 7
- تعارض‌های باز بخش 6: 12
- Rule Candidate: 0
- نتیجه: `EVIDENCE_INCOMPLETE / CONFLICT_OPEN / LICENSING_HOLD`

## تفکیک ضروری شواهد

سه موضوع نباید با هم مخلوط شوند:

1. وجود شکاف در review درمان پس از severe hypoglycemia؛
2. توانایی intervention برای افزایش deprescribing یا simplification؛
3. اثربخشی و ایمنی بالینی یک medication action مشخص پس از یک رخداد تأییدشده.

مطالعات مستقیم پس از رخداد عمدتاً مورد اول را نشان می‌دهند و اثبات نمی‌کنند که یک اقدام دارویی مشخص recurrence، hospitalization یا mortality را در کل جمعیت کاهش می‌دهد.

## شواهد مستقیم فرایندی پس از رخداد

### Alexopoulos et al., 2021

Retrospective claims cohort در سالمندان پس از ED/hospitalization مرتبط با severe hypoglycemia. مطالعه نشان می‌دهد deintensification به‌طور یکنواخت انجام نمی‌شود و با regimen و ویژگی‌های بیمار متفاوت است. Outcome اصلی process است، تغییر دوز insulin ممکن است ثبت نشود و causal benefit بررسی نشده است.

Preliminary ROBINS-I برای causal inference: `SERIOUS`

منبع: https://pmc.ncbi.nlm.nih.gov/articles/PMC8564578/

### Vijayakumar et al., 2020

Retrospective pre/post analysis. پس از severe hypoglycemia، بسیاری از اجزای مدیریت بدون تغییر باقی ماندند. مطالعه comparator causal ندارد، A1C فقط برای زیرمجموعه‌ای موجود است و medication dose/adherence کامل ثبت نمی‌شود.

Preliminary ROBINS-I: `SERIOUS`

نتیجهٔ این گروه: care-process gap محتمل است؛ action-specific efficacy اثبات نشده است.

## شواهد غیرمستقیم مداخله‌ای

### Munshi et al., 2016

مطالعهٔ تک‌گروهی کوچک در سالمندان insulin-treated. پس از simplification، CGM hypoglycemia و burden کاهش یافت، اما comparator وجود نداشت و event-triggered نبود.

Preliminary ROBINS-I: `SERIOUS`

### IMPERIUM, 2018

Randomized open-label trial در سالمندان آسیب‌پذیر. یک strategy با خطر hypoglycemia کمتر چند outcome هیپوگلیسمی را کاهش داد. prior Level 2/3 event شرط ورود نبود و تعمیم به همهٔ داروها مجاز نیست.

Preliminary RoB 2: `SOME_CONCERNS`

### Grant et al., 2025

Cluster randomized trial. مداخلهٔ clinician-facing نرخ deprescribing را افزایش داد، اما کاهش قطعی hypoglycemia complication را اثبات نکرد. این شواهد برای workflow مهم است، نه medication action خودکار.

Preliminary RoB 2 cluster: `SOME_CONCERNS`

منبع: https://jamanetwork.com/journals/jamainternalmedicine/fullarticle/2835615

## ترجیحات بیمار

Pilla et al. نشان می‌دهد willingness برای deintensification به وضعیت سلامت و خطر hypoglycemia وابسته است. این مطالعه برای acceptability مفید است، نه efficacy؛ قابلیت تعمیم به ایران نیز محدود است.

## مرور نظام‌مند

Seidu et al. برای feasibility/safety deprescribing مرتبط است، اما AMSTAR 2 و mapping مطالعات پایه هنوز تکمیل نشده است. ناهمگنی population، intervention و outcome باید حل شود.

Status: `FULLTEXT_ROB_PENDING`

## Safety conflict

### Christiaens et al., 2025

Target-trial emulation در افراد 75 سال و بالاتر. در routine data، deintensification با افزایش کوتاه‌مدت composite مرگ یا hospitalization همراه بود. این یافته نادیده گرفته نمی‌شود؛ در عین حال confounding by indication، reverse causation، frailty، افت سلامت، prognosis و acute illness می‌توانند association را به‌شدت مخدوش کنند.

Preliminary ROBINS-I برای ادعای causal: `CRITICAL`

منبع: https://pmc.ncbi.nlm.nih.gov/articles/PMC12156012/

تصمیم: broad deintensification تا formal ROBINS-I، بررسی correction، sensitivity analysis و triangulation در HOLD می‌ماند.

## شکاف اصلی

هنوز شواهد مستقیم کافی شناسایی نشده که ثابت کند پس از یک رخداد تأییدشدهٔ Level 2/3، یک medication action استاندارد و مشخص در همهٔ بزرگسالان recurrence یا net harm را کاهش می‌دهد. citation-chain و supplemental search ادامه دارد.

## تعارض cardiorenal

بازنگری دارو نباید therapy دارای منفعت مستقل برای CKD، HF، ASCVD یا obesity را بدون بررسی indication حذف کند. drug class، indication، eGFR، بیماری‌های همراه و individualized goal اجباری‌اند.

## نتیجه برای موتور

احتمالاً فقط یک trigger محدود clinician-owned برای review پس از رخداد تأییدشده قابل پژوهش است. این trigger نیز نیازمند false-positive، duplicate suppression، owner/SLA، retrospective و SILENT validation است.

موارد ممنوع:

- کاهش خودکار insulin؛
- قطع sulfonylurea؛
- تعویض خودکار class؛
- تغییر خودکار target؛
- prescription/order؛
- پیام مستقیم درمانی.

## Gate

- `SCIENTIFIC_DIRECTNESS = INCOMPLETE`
- `SAFETY_CONFLICT = OPEN`
- `FORMAL_ROB = INCOMPLETE`
- `CROSS_SECTION_REVIEW = INCOMPLETE`
- `LOCAL_VALIDATION = NOT_STARTED`
- `LICENSING = HOLD`
- `RULE_CANDIDATE = NO`
