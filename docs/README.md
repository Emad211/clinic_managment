# 📚 مستنداتِ پروژه (Docs Index)

این پوشه، «مغزِ» تصمیم‌های محصول، استراتژی و فنیِ استارت‌آپ است — هر بخش یک فایلِ MD که **همیشه یادمان می‌ماند**. هر تصمیمِ مهم اینجا ثبت و تاریخ‌دار می‌شود.

> برای راهنمای **کدِ موجود** (نحوهٔ کار، اجرا، معماریِ فعلیِ دو اپ) به `../CLAUDE.md` در ریشهٔ ریپو نگاه کن. این پوشه دربارهٔ **چرا** و **به کجا می‌رویم** است.

## نقشهٔ اسناد
| سند | موضوع | وضعیت |
|---|---|---|
| [`MASTER_PLAN.md`](MASTER_PLAN.md) | ⭐ سندِ مرجعِ محصول و استراتژی (چشم‌انداز، استراتژیِ نردبان، ماژول‌ها، نقشهٔ راه، مدلِ کسب‌وکار، معماریِ پایپ‌لاین) | زنده |
| [`TECH_STACK.md`](TECH_STACK.md) | تصمیمِ نهاییِ استکِ فنی + دلیلِ هر انتخاب + نقشهٔ مهاجرت | قفل‌شده v1.0 |
| [`MARKET_RESEARCH.md`](MARKET_RESEARCH.md) | تحقیقِ سیتیشن‌دارِ بازار/رقبا/قانون (مبنای استراتژی) | خرداد۱۴۰۵ |
| [`FEATURES.md`](FEATURES.md) | مشخصاتِ دقیقِ فیچرهای فاز۱ (epic / user-story / معیارِ پذیرش) | زنده v0.1 |
| [`EPRESCRIPTION.md`](EPRESCRIPTION.md) | امکان‌سنجی و تصمیمِ اتصالِ نسخهٔ الکترونیک (Spike Epic 1) | v1.0 |
| [`DATA_MODEL.md`](DATA_MODEL.md) | مدلِ یکپارچهٔ Postgres + multi-tenancy (RLS) + نگاشتِ مهاجرت | زنده v0.1 |
| [`PIPELINE.md`](PIPELINE.md) | معماریِ build-readyِ پایپ‌لاینِ استخراجِ دانش (فاز۰/رتبهٔ۳) — ۹ لایه، توپولوژیِ سرویس، مدلِ داده، ترتیبِ ساخت | زنده v0.1 |

## اسنادِ آینده (هنوز ساخته نشده)
- `REGULATORY.md` — جزئیاتِ مجوز/انطباق و چک‌لیستِ سپر.

## وضعیتِ پیاده‌سازی (کد)
- **`../ai_service/`** — سرویسِ **پایپ‌لاینِ دانش** (FastAPI+arq، فاز۰/رتبهٔ۳، خندقِ بلندمدت). **M2 (v0.2):** Model Gateway (AvalAI+NullModel)، Ingestion با dedupِ هش‌محور، **پارسِ ساختاریِ PyMuPDF** (متن+جدول→DocumentChunk با page anchor)، `/health`+`/ingest`، ۱۰ تست سبز. معماری: [`PIPELINE.md`](PIPELINE.md). راهنما: [`../ai_service/README.md`](../ai_service/README.md).
- **`../platform/`** — اسکلتِ **Django + django-ninja + PostgreSQL** (مقصدِ Evolve-not-Rewrite). نسخهٔ **v0.9 (دموپذیر)**: **هر ۸ ماژولِ DATA_MODEL §2** (≈۴۰ مدل)، **RLS**، API با **login + روترهای گاردشده**، **ETLِ کامل** (بیماران+vitals/meds/conditions/flags/followups) + **ETLِ کاتالوگ** (۵۷ قاعدهٔ ADA)، **موتورِ قاعده** با decision supportِ زنده، **frontendِ وب** با سه گردشِ کارِ مزمن (**Snapshot** + **پیشنهادهای ADA** +ack→SuggestionLog + **کارتابلِ Recall**) و **گردشِ کارِ نسخهٔ الکترونیک** (Epic 1، پلِ WebView). **یادآورِ پیامکی (Epic 6)** + **حلقهٔ اشتراک/پرداختِ SaaS (ZarinPal، Epic 0)** — کلِ حلقهٔ onboard→subscribe→charge→deliver. **RLS روی Postgresِ واقعی اثبات شد** (`verify_rls`)؛ **Docker + CIِ GitLab** آماده. همگی e2e تأیید شدند؛ اپ‌های Flaskِ کارا دست‌نخورده. راهنما: [`../platform/README.md`](../platform/README.md). مبنا: [`DATA_MODEL.md`](DATA_MODEL.md).

## اصلِ کار
**نردبان:** اول گوهِ مزمن (درآمدِ سریع) → لایهٔ هوشِ بالینی (تمایز) → پلتفرمِ دانش (خندقِ بلندمدت). جزئیات در `MASTER_PLAN.md`.
