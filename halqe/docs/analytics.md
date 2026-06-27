# آنالیتیکسِ privacy-first (قدم ۵۹)

> اصل: حریمِ بیمار و کلینیک بالاتر از hype. **هیچ Google Analytics، هیچ شخص‌ثالثِ
> خارجی، هیچ trackingِ پیش‌فرض.** آنالیتیکس فقط برای **سایتِ بازاریابیِ عمومی**
> است — هرگز برای پنلِ احرازشده یا دادهٔ بیمار.

## انتخاب: Plausible یا Umami (self-hosted)
- **چرا نه Google Analytics:** داده را به شخص‌ثالثِ خارجی می‌فرستد، با cookie و
  ردیابیِ فردی — ناسازگار با روایتِ **اعتمادِ داده** ([ADR-0006](adr/0006-cloud-unification-and-data-trust.md))
  و حریمِ بیمار. برای میزبانیِ ایران هم نامناسب.
- **Plausible** (یا **Umami**): سبک، **cookie-less**، بدونِ دادهٔ شخصی، **self-hosted**
  روی همان VPS (قدم ۵۵) → هیچ داده‌ای از مرزِ شما خارج نمی‌شود. فقط سنجه‌های تجمیعیِ
  بازدیدِ صفحه (page views، referrer، کشور در سطحِ کلان) — بدونِ PII، بدونِ fingerprint.
- پیشنهاد: **Plausible Community Edition** (self-hosted، Docker) یا **Umami** (Node+Postgres).
  هر دو با compose روی VPS بالا می‌آیند؛ از همان Postgres یا یک نمونهٔ جدا استفاده کن.

## دامنهٔ ردیابی (حد و مرز)
- ✅ فقط صفحهٔ فرودِ **عمومی** (`/`). 
- ⛔ **هرگز** پنلِ احرازشده: `/dashboard`, `/patients`, `/worklist`, `/manager/*`,
  `/card/*`, `/report/*`, `/queue`. (اسکریپتِ آنالیتیکس عمداً فقط در `src/app/page.tsx`
  است، نه در `layout.tsx`ِ مشترک — پس روی هیچ صفحهٔ احرازشده‌ای بارگذاری نمی‌شود.)
- ⛔ هیچ PII، national_id، یا دادهٔ بیمار هرگز ارسال نمی‌شود (سایتِ بازاریابی داده‌ی
  بیمار ندارد).

## فعال‌سازی (env-gated، پیش‌فرض خاموش)
اسکریپتِ آنالیتیکس **فقط** وقتی بارگذاری می‌شود که هر دو متغیرِ زیر در زمانِ `next build`
ست شده باشند (مثلاً در `.env.production` یا env سرور):

| متغیر | مثال | توضیح |
|---|---|---|
| `NEXT_PUBLIC_ANALYTICS_DOMAIN` | `halqe.app` | دامنه‌ای که در پنلِ Plausible/Umami ثبت کرده‌اید |
| `NEXT_PUBLIC_ANALYTICS_SRC` | `https://analytics.halqe.app/js/script.js` | آدرسِ اسکریپتِ نمونهٔ **self-hostedِ خودتان** |

با نبودِ این دو (توسعه / پیکربندی‌نشده) → **هیچ اسکریپتی، هیچ trackingی، هیچ درخواستِ
شخص‌ثالثی** (آفلاینِ توسعه دست‌نخورده). جای تعریف: `src/app/page.tsx` (بلوکِ گِیت‌دار).

## گام‌های میزبانیِ self-hosted روی VPS (قدم ۵۵)
1. سرویسِ Plausible/Umami را در `docker-compose.yml`ِ production اضافه کن (یا compose جدا)؛
   پشتِ همان nginx با TLS (subdomain مثلِ `analytics.halqe.app`).
2. دامنه را در پنلِ آن ثبت کن → آدرسِ اسکریپت را بگیر.
3. `NEXT_PUBLIC_ANALYTICS_DOMAIN` + `NEXT_PUBLIC_ANALYTICS_SRC` را در env ست کن و
   فرانت را **rebuild** کن (`/` استاتیک است؛ اسکریپت در زمانِ build تزریق می‌شود).
4. تأیید کن فقط روی `/` بارگذاری می‌شود (نه پنل) و cookie/PII ندارد.

## ⛔ گِیتِ مالک / ops
- **VPS:** نمونهٔ self-hostedِ analytics تا تهیهٔ VPSِ ایرانی (قدم ۵۵) میزبانی نشده.
- انتخابِ نهاییِ Plausible vs Umami + subdomain با مالک.
- تا آن زمان، آنالیتیکس **خاموش** است و سایت بدونِ هیچ trackingی کار می‌کند.
