# پایپ‌لاینِ استخراجِ دانشِ بالینی (فاز ۰ / رتبهٔ ۳ نردبان)

> **نسخه ۰.۱ — خرداد۱۴۰۵ — معماریِ build-ready.** خندقِ بلندمدتِ استارت‌آپ.
> مرجع: [`MASTER_PLAN.md`](MASTER_PLAN.md) §۷ · [`TECH_STACK.md`](TECH_STACK.md) · memory `knowledge_pipeline.md`.
>
> **هدف:** از PDF/گایدلاینِ انگلیسیِ معتبر → **گرافِ دانشِ قابلِ‌کوئری** برای تغذیهٔ سه ماژولِ پلتفرم (آموزش/تشخیص/درمان).
> **اصلِ حاکم:** هر تکه دانش یک **«ادعا» (claim)** است که باید به منبعش گره بخورد و از **گیتِ تأیید** رد شود؛
> وگرنه به **صفِ بازبینیِ انسانی** می‌رود. خروجیِ «بدونِ ایهام» از **معماری** می‌آید، نه از پرامپت.

## ۰. رابطه با کدِ موجود (مهم)
موتورِ `apps/chronic/rule_engine.py` + کاتالوگِ ۵۷ قاعدهٔ ADA عملاً یک **برشِ عمودیِ دستی‌سازِ همین پایپ‌لاین** است:
دانشِ بالینی به‌صورتِ ساختاریافته (`trigger_json` + recommendation/dosage/monitoring) که به منبع (`source_ref`) گره خورده.
پایپ‌لاین همان را **خودکار و در مقیاسِ کلِ پزشکی** از گایدلاین‌ها می‌سازد. این پیوستگی دارایی است: خروجیِ نهاییِ
پایپ‌لاین می‌تواند هم‌قالبِ `ClinicalRule` باشد و مستقیماً موتورِ موجود را تغذیه کند.

## ۱. توپولوژیِ سرویس (کجا اجرا می‌شود)
سرویسِ جداگانه از مونولیتِ Django (تا بارِ LLM و چرخهٔ توسعهٔ متفاوت، اپِ کلینیک را کند/ناپایدار نکند):

```
platform/ (Django + ninja)  ── کلینیک، RLS، سروینگِ نهایی به UI
ai_service/ (FastAPI + arq) ── پایپ‌لاینِ دانش (این سند)
        ├─ arq workers      ── کارگرهای async برای هر لایه (LLM-bound)
        ├─ Redis            ── صفِ arq + کشِ هش‌محور
        └─ PostgreSQL+pgvector ── منبعِ حقیقتِ دانش (مشترک یا instance جدا)
AvalAI (OpenAI-compatible)  ── دروازهٔ مدل (پشتِ Model Gateway)
```
- **چرا FastAPI+arq نه Celery:** کارِ پایپ‌لاین I/O-bound و LLM-heavy است؛ arq سبک و async-native. (Celery برای jobهای کلینیک در فاز۱.)
- **مرزِ داده:** جداولِ دانش از جداولِ کلینیک جدا (schemaِ `knowledge`)؛ **بدونِ RLS** (دانشِ جهانی، نه per-tenant) — برخلافِ دادهٔ بیمار.

## ۲. نُه ایستگاه (Layer 0→9) و نگاشت به کد
| # | لایه | جنس | پیاده‌سازی |
|---|---|---|---|
| 0 | **Model Gateway** | انتزاع روی AvalAI | `ai_service/gateway/` — کلاینتِ OpenAI-compatible؛ per-layer model+budget؛ retry/timeout؛ ردگیریِ هزینه |
| 1 | **Ingestion & Registry** | قطعی | `source_document` + **هشِ محتوا** (نسخه‌بندی/کش/تشخیصِ تکراری) + متادیتا (ناشر/سال/نهاد/سطحِ شواهد) |
| 2 | **Structural Parsing** | قطعی، قبل از LLM | PyMuPDF/pdfplumber متن؛ **Camelot/Tabula جدول‌ها** (آبجکتِ ساختاریافته — دوز در جدول است)؛ تصویر+کپشن؛ OCR فقط برای اسکن. خروجی: بازنماییِ نرمال با **لنگرِ صفحه** |
| 3 | **Chunking & Routing** | LLM سبک | قطعه‌بندیِ معناییِ بخش‌محور (نه پنجرهٔ توکن) + طبقه‌بندیِ نوع/سطحِ شواهد/حوزه → مسیردهی |
| 4 | **Specialized Extraction** | ایجنت‌های موازی، LLM قوی | ترمینولوژی→واقعیتِ بالینی→دارو→آموزشی. هر ایجنت اول **متنِ میانیِ خوانا** سپس JSON. قانون: **هر ادعای اتمی لنگرِ منبع دارد** |
| 5 | **Verification & Grounding** | **گیتِ بحرانی** | ایجنتِ **مستقل** که خروجی را بی‌اعتماد فرض می‌کند؛ هر ادعا را برابرِ متنِ همان لنگر چک می‌کند → حکم (تأیید/نسبی/یافت‌نشد/متناقض)+اطمینان+اسنیپت. شکست→۱ retry→صفِ انسانی |
| 6 | **Ontology Mapping** | قطعی + LLM-fallback | رزالو به **شناسهٔ کانونیِ داخلی** + کراس‌واک به ICD-11/MeSH/INN/ATC؛ entity-resolution |
| 7 | **Graph Build & Conflict** | قطعی | گره/یال با provenance؛ تعارض **بازنویسی نمی‌شود** (هر دو با فلگ+شواهد+تازگی)؛ خوشه‌بندیِ Leiden؛ نسخه‌بندی |
| 8 | **Multi-Engine Storage** | — | **Postgres = منبعِ حقیقت** (claimهای تأییدشده، append-only، نسخه‌دار) + pgvector؛ Neo4j/Object = projectionِ قابلِ‌بازسازی |
| 9 | **Serving** | API به سبکِ **MCP** | `get_concept/get_neighbors/get_differential`؛ ترجمهٔ EN→FA **فقط زمانِ نمایش** |

## ۳. ارکستریتور (ستونِ فقرات)
الگوی **Orchestrator–Worker**: آبجکتِ وضعیتِ job، dispatch کارگرها، **اجرای گیت‌ها** (تا تأیید نشود ایستگاهِ بعد ممنوع)،
retry، هدایتِ شکست به صفِ انسانی. باید **idempotent + resumable + observable** باشد (لاگ/متریک/ردگیریِ هزینه به‌تفکیکِ ایستگاه).
هر سندْ یک state machine: `ingested → parsed → chunked → extracted → verified → mapped → graphed → served` (+ `needs_review` در هر گام).

## ۴. مدلِ دادهٔ دانش (Postgres schema `knowledge`) — DDLِ هسته
```sql
CREATE TABLE source_document (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT, publisher TEXT, year INT, evidence_level TEXT,
  content_hash TEXT UNIQUE,            -- پایهٔ کش/نسخه/تشخیصِ تکراری
  status TEXT NOT NULL DEFAULT 'ingested',
  meta JSONB, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE document_chunk (          -- خروجیِ لایهٔ ۲+۳
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID REFERENCES source_document(id),
  ordinal INT, page_anchor INT,        -- لنگرِ صفحه (مبنای تأیید)
  kind TEXT,                           -- prose|table|figure_caption
  content TEXT, structured JSONB,      -- جدول‌ها به‌صورتِ آبجکت
  domain TEXT, evidence_level TEXT
);
CREATE TABLE claim (                    -- «ادعا»ی اتمی (خروجیِ لایهٔ ۴، append-only)
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  chunk_id UUID REFERENCES document_chunk(id),
  claim_type TEXT,                     -- terminology|clinical_fact|drug|education
  payload JSONB,                       -- محتوای ساختاریافته
  source_anchor JSONB,                 -- {document_id, page, snippet}
  status TEXT NOT NULL DEFAULT 'extracted',  -- extracted|verified|partial|not_found|conflicting|needs_review
  confidence REAL, version INT DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE verification (             -- خروجیِ گیتِ بحرانی (لایهٔ ۵)
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id UUID REFERENCES claim(id),
  verdict TEXT, confidence REAL, supporting_snippet TEXT,
  model TEXT, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE chunk_embedding (          -- pgvector
  chunk_id UUID PRIMARY KEY REFERENCES document_chunk(id),
  embedding vector(1536)
);
CREATE TABLE ontology_concept (         -- لایهٔ ۶ (شناسهٔ کانونی + کراس‌واک)
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_name TEXT, icd11 TEXT, mesh TEXT, inn TEXT, atc TEXT,
  aliases JSONB
);
CREATE TABLE graph_node (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  concept_id UUID REFERENCES ontology_concept(id), kind TEXT, props JSONB);
CREATE TABLE graph_edge (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  src UUID REFERENCES graph_node(id), dst UUID REFERENCES graph_node(id),
  rel TEXT, provenance JSONB, evidence_level TEXT, version INT DEFAULT 1);
CREATE TABLE review_queue (             -- حلقهٔ بازبینیِ انسانی (کامپوننتِ درجه‌یک)
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id UUID REFERENCES claim(id), reason TEXT,
  assigned_to TEXT, resolved BOOLEAN DEFAULT false, created_at TIMESTAMPTZ DEFAULT now());
```

## ۵. اجزای جدانشدنی (از روزِ اول طراحی شوند)
- **حلقهٔ بازبینیِ انسانی:** آیتم‌های ایمنی‌حساس (دوز/منع‌مصرف) **همیشه** بازبینی، فارغ از امتیازِ اطمینان. بازبینی→بهبودِ پرامپت (یادگیریِ فعال).
- **Gold Set:** بنچمارکِ هر تغییرِ پرامپت/مدل + بذرِ لایهٔ تأیید.
- **کشِ هش‌محور:** محتوای بدون‌تغییر = بدونِ هزینهٔ API.
- **سطح‌بندیِ مدل:** ارزان=طبقه‌بندی/مسیریابی، قوی=استخراج/تأیید (بودجه per-layer در Gateway).

## ۶. تصمیمات
- **قفل‌شده:** عدمِ‌قفل به آنتولوژیِ واحد (کانونی+کراس‌واک)؛ deterministic-first + LLM-fallback؛ Postgres منبعِ حقیقت؛ ترجمه فقط نمایش.
- **هشدارِ تحریم:** SNOMED (ایران عضو نیست) و ابزارهای NIH (UMLS/RxNorm) ممکن است محدود باشند → پایه **ICD-11 + MeSH + INN + ATC**.
- **الهام از graphify** (MIT): سرورِ MCP گراف، خوشه‌بندیِ Leiden، اسکیمای graph.json — ولی **نه** هستهٔ تولیدی (فاقدِ آنتولوژیِ پزشکی/تأییدِ مستقل/استخراجِ جدولِ دوز/نسخه‌بندی).
- **باز:** سیاستِ دقیقِ حلِ تعارض (تازگی vs سطحِ شواهد)؛ مدلِ embedding (بُعدِ ۱۵۳۶ فرضی — با AvalAI نهایی شود).

## ۷. ترتیبِ ساخت (Build Order) — اولین مایلستون مشخص
1. **M1 — اسکلتِ `ai_service` + Model Gateway + Ingestion + Storage:** FastAPI + arq + Redis؛ `gateway` (AvalAI client با per-layer config)؛ جداولِ `source_document`/`document_chunk`/`claim`؛ آپلودِ یک PDF → ثبت + هش. **verify: یک سند ingest و در DB ثبت شود.**
2. **M2 — Structural Parsing (قطعی):** PyMuPDF متن + Camelot جدول + لنگرِ صفحه → `document_chunk`. (بدونِ LLM؛ قابلِ‌تستِ کامل.)
3. **M3 — Extraction + Verification gate:** ایجنتِ استخراجِ ترمینولوژی → `claim`؛ ایجنتِ مستقلِ تأیید → `verification`؛ ارکستریتورِ idempotent. **بذرِ Gold Set.**
4. **M4 — Ontology + Graph + Serving (MCP):** نگاشت، گراف، API. تغذیهٔ ماژولِ آموزش (فاز۲).
> اصل: تا **M3 (گیتِ تأیید) پایدار** نشود، مقیاس نده — کیفیتِ ادعاها مهم‌تر از حجم است.

## ۸. ریسک‌ها
- هزینهٔ LLM (با سطح‌بندیِ مدل + کشِ هش‌محور کنترل می‌شود).
- کیفیتِ استخراج (با گیتِ تأیید + Gold Set + بازبینیِ انسانی).
- دسترسیِ آنتولوژی‌های NIH از ایران (پایهٔ ICD-11/MeSH/INN/ATC).
- پیچیدگی: **MVP تک‌حوزه** (مثلاً دیابت — هم‌راستا با دادهٔ موجودِ کلینیک) قبل از تعمیم.
