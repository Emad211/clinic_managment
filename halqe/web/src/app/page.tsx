import type { Metadata } from "next";
import Link from "next/link";
import styles from "./landing.module.css";

/**
 * Public marketing landing page for «حلقه» (Halqe) — the new "/".
 *
 * Server-rendered, RTL/Persian, no client JS, no external CDN.
 * Every claim here is grounded in `halqe/docs/demo_script.md` (step 57,
 * advisor-vetted). HONESTY is load-bearing:
 *   - NO causal / lift / ROI percentages ("X% more patients").
 *   - NO "AI" / "automatic diagnosis" language → "موتورِ پیشنهادِ بالینیِ
 *     مبتنی بر گایدلاین، تصمیم با پزشک".
 *   - Decision support is suggestion-only: «پیشنهاد — تأیید با پزشک».
 *   - Accounting data is READ-ONLY; nothing is written back.
 *   - No SMS without the clinic's approval; KYC-gated.
 *   - Never claim a feature that isn't built (e.g. there is NO /control-room
 *     page). Only real, shipped features are described.
 *
 * The data-trust story (read-only boundary + consent + no fabricated numbers)
 * IS the differentiator — it is foregrounded, not buried.
 */

// Page-level metadata — extends the base metadata from layout.tsx without
// overriding the metadataBase / fonts / manifest set there.
export const metadata: Metadata = {
  title: "حلقه — بازگرداندنِ بیمارانِ مزمن، با احترام به دادهٔ کلینیک",
  description:
    "حلقه بیمارانِ مزمنی را که بی‌سروصدا پیگیری‌شان قطع شده شناسایی و بازمی‌گرداند. پرونده از حسابداریِ فعلیِ شما فقط خواندنی پر می‌شود، پیشنهادهای بالینی مبتنی بر گایدلاین‌اند و تصمیم همیشه با پزشک است، و هیچ پیامکی بدونِ اجازهٔ شما ارسال نمی‌شود.",
  keywords: [
    "مدیریت بیماری مزمن",
    "دیابت",
    "فشار خون",
    "پیگیری بیمار",
    "حلقهٔ مراقبت",
    "پشتیبانِ تصمیمِ بالینی",
    "نرم‌افزار کلینیک",
    "حلقه",
  ],
  alternates: {
    canonical: "/",
  },
  openGraph: {
    title: "حلقه — بازگرداندنِ بیمارانِ مزمن، با احترام به دادهٔ کلینیک",
    description:
      "شناسایی و بازگرداندنِ بیمارانِ مزمنِ در حالِ ریزش. پرونده فقط‌خواندنی از حسابداری، پیشنهادِ بالینی با تأییدِ پزشک، و پیامک فقط با اجازهٔ کلینیک.",
    type: "website",
    locale: "fa_IR",
    siteName: "حلقه",
  },
};

// ── schema.org JSON-LD ──────────────────────────────────────────────
// Honest fields only: no rating, no offer/price, no install count, no claim
// of a feature that isn't built. SoftwareApplication describes the platform;
// Organization describes the brand.
const jsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "SoftwareApplication",
      name: "حلقه",
      applicationCategory: "HealthApplication",
      operatingSystem: "Web",
      inLanguage: "fa-IR",
      description:
        "سامانهٔ مدیریت بیماری‌های مزمن برای کلینیک‌ها: پروندهٔ بیماری‌محور که از حسابداریِ موجود فقط‌خواندنی پر می‌شود، موتورِ پیشنهادِ بالینیِ مبتنی بر گایدلاین با تصمیمِ نهاییِ پزشک، حلقهٔ پیگیری تا ویزیت، و پیام‌رسانیِ مبتنی بر رضایت.",
      featureList: [
        "پروندهٔ بیماری‌محورِ مزمن",
        "خواندنِ فقط‌خواندنیِ دادهٔ حسابداری",
        "موتورِ پیشنهادِ بالینی (تصمیم با پزشک)",
        "حلقهٔ پیگیری: اندازه‌گیری، پیشنهاد، پیگیری، ویزیت",
        "پیام‌رسانیِ مبتنی بر رضایت و تأیید",
        "جداسازیِ چندمستأجره",
      ],
    },
    {
      "@type": "Organization",
      name: "حلقه",
      url: "https://halqe.app",
      description:
        "پلتفرمِ مدیریتِ بیماری‌های مزمن با احترام به حریمِ دادهٔ کلینیک.",
    },
  ],
};

export default function LandingPage() {
  return (
    <div className={styles.page}>
      {/* JSON-LD structured data (sanitized via JSON.stringify) */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      {/*
        Privacy-first analytics (step 59) — DEFAULT OFF, public landing ONLY.

        Rendered ONLY when BOTH env vars are set at build time, pointing at the
        owner's SELF-HOSTED Plausible/Umami instance (NOT Google Analytics, no
        external third party — see docs/analytics.md + the data-trust ADR-0006).
        With no env (dev / not configured) NOTHING is loaded → zero tracking,
        zero third-party request, offline-clean. This lives on the public
        marketing page only — it is NEVER placed in the shared layout, so the
        authenticated panel (/dashboard, /patients, …) is never tracked and no
        PII/patient data ever reaches it.
      */}
      {process.env.NEXT_PUBLIC_ANALYTICS_SRC &&
        process.env.NEXT_PUBLIC_ANALYTICS_DOMAIN && (
          <script
            defer
            data-domain={process.env.NEXT_PUBLIC_ANALYTICS_DOMAIN}
            src={process.env.NEXT_PUBLIC_ANALYTICS_SRC}
          />
        )}

      {/* ── Top bar ── */}
      <header className={styles.topbar}>
        <span className={styles.topbarBrand}>حلقه</span>
        <nav className={styles.topbarActions} aria-label="ناوبریِ اصلی">
          <Link
            href="/login"
            className={`${styles.btnPrimary} ${styles.btnSmall}`}
          >
            ورود به پنل
          </Link>
        </nav>
      </header>

      <main>
        {/* ── Hero ── */}
        <section className={styles.hero} aria-labelledby="hero-title">
          <div className={styles.heroInner}>
            <h1 id="hero-title" className={styles.heroTitle}>
              <span className={styles.heroBrand}>حلقه</span> بیمارانِ مزمنی را که
              بی‌سروصدا از مطب می‌روند، بازمی‌گرداند
            </h1>
            <p className={styles.heroLead}>
              پرونده‌ای که از حسابداریِ فعلیِ شما فقط <strong>خواندنی</strong> پر
              می‌شود، و پیشنهادهای بالینی‌ای که تصمیمش{" "}
              <strong>همیشه با پزشک</strong> است. مراقبتِ بهترِ بیمارِ مزمن، بدونِ
              دست‌زدن به دادهٔ حسابداری و بدونِ یک پیامکِ بدونِ‌اجازه.
            </p>

            <ul className={styles.heroPoints}>
              <li className={styles.heroPoint}>پل حسابداری فقط‌خواندنی</li>
              <li className={styles.heroPoint}>پیشنهاد — تأیید با پزشک</li>
              <li className={styles.heroPoint}>پیامک فقط با اجازهٔ شما</li>
            </ul>

            <div className={styles.heroCtas}>
              <Link href="/login" className={styles.btnPrimary}>
                ورود به پنل
              </Link>
              <a href="#demo" className={styles.btnSecondary}>
                درخواست دمو
              </a>
            </div>
          </div>
        </section>

        {/* ── The care loop ── */}
        <section
          className={styles.loopSection}
          aria-labelledby="loop-title"
        >
          <div className={styles.section}>
            <h2 id="loop-title" className={styles.sectionTitle}>
              حلقهٔ مراقبت، بسته می‌شود
            </h2>
            <p className={styles.sectionLead}>
              پیگیری وقتی ارزش دارد که به نوبت برسد. حلقه این مسیر را گام‌به‌گام
              می‌بندد — همان چرخه‌ای که در پنل اجرا می‌شود.
            </p>
            <ol className={styles.loopSteps}>
              <li className={styles.loopStep}>
                <span className={styles.loopStepNum} aria-hidden="true">
                  ۱
                </span>
                <span className={styles.loopStepLabel}>اندازه‌گیری</span>
              </li>
              <li className={styles.loopStep}>
                <span className={styles.loopStepNum} aria-hidden="true">
                  ۲
                </span>
                <span className={styles.loopStepLabel}>پیشنهاد</span>
              </li>
              <li className={styles.loopStep}>
                <span className={styles.loopStepNum} aria-hidden="true">
                  ۳
                </span>
                <span className={styles.loopStepLabel}>پیگیری</span>
              </li>
              <li className={styles.loopStep}>
                <span className={styles.loopStepNum} aria-hidden="true">
                  ۴
                </span>
                <span className={styles.loopStepLabel}>ویزیت</span>
              </li>
              <li className={styles.loopStep}>
                <span className={styles.loopStepNum} aria-hidden="true">
                  ۵
                </span>
                <span className={styles.loopStepLabel}>تکرار</span>
              </li>
            </ol>
          </div>
        </section>

        {/* ── Features (real, shipped) ── */}
        <section className={styles.section} aria-labelledby="features-title">
          <h2 id="features-title" className={styles.sectionTitle}>
            چه چیزی واقعاً ساخته شده است
          </h2>
          <p className={styles.sectionLead}>
            فقط ویژگی‌هایی که در پنل هست را توصیف می‌کنیم — نه وعده، نه عددِ
            اثبات‌نشده.
          </p>

          <div className={styles.featureGrid}>
            <article className={styles.featureCard}>
              <span className={styles.featureKicker}>تصمیم با پزشک</span>
              <h3>موتورِ پیشنهادِ بالینی</h3>
              <p>
                موتورِ پیشنهادِ بالینیِ مبتنی بر گایدلاین، حواسِ پزشک را به
                نکته‌های مهمِ پرونده جمع می‌کند. این سامانه تشخیص یا تجویز نمی‌کند؛
                هر پیشنهاد با برچسبِ «پیشنهاد — تأیید با پزشک» می‌آید و تصمیمِ
                نهایی همیشه با پزشکِ شماست. هشدارهای فوری بی‌درنگ بالا می‌آیند.
              </p>
            </article>

            <article className={styles.featureCard}>
              <span className={styles.featureKicker}>حریمِ دادهٔ کلینیک</span>
              <h3>پل حسابداری، فقط‌خواندنی</h3>
              <p>
                پروندهٔ بیمار از حسابداریِ فعلیِ شما به‌صورتِ زنده و فقط‌خواندنی پر
                می‌شود. حلقه چیزی در دادهٔ حسابداری نمی‌نویسد و تغییری نمی‌دهد —
                مرزِ داده محفوظ می‌ماند.
              </p>
            </article>

            <article className={styles.featureCard}>
              <span className={styles.featureKicker}>رضایتِ بیمار</span>
              <h3>پیامک فقط با اجازهٔ شما</h3>
              <p>
                هیچ پیامکی بدونِ تأییدِ کلینیک ارسال نمی‌شود؛ هر پیام را یکی‌یکی
                مرور و تأیید می‌کنید. تا احرازِ هویتِ سامانهٔ پیامکی (KYC) کامل
                نشود، هیچ پیامِ واقعی نمی‌رود. اختیارِ کامل دستِ کلینیک است.
              </p>
            </article>

            <article className={styles.featureCard}>
              <span className={styles.featureKicker}>پروندهٔ بیماری‌محور</span>
              <h3>پروندهٔ مزمنِ یکپارچه</h3>
              <p>
                هر بیماریِ مزمن (دیابت، فشار خون و…) بخش‌ها و داده‌های خود را به
                پرونده اضافه می‌کند: ویتال‌ها، آزمایش‌ها، داروها و وضعیتِ کنترل،
                در یک نمای منسجم.
              </p>
            </article>

            <article className={styles.featureCard}>
              <span className={styles.featureKicker}>گزارشِ صادقانه</span>
              <h3>گزارش‌های توصیفی، نه ادعای علّی</h3>
              <p>
                گزارش‌ها توصیفی‌اند و صریح می‌گویند اثباتِ علّی نیستند. جای دادهٔ
                کم، عدد نمی‌سازیم؛ می‌نویسیم «دادهٔ ناکافی». این صداقت، خودِ
                تمایزِ ماست.
              </p>
            </article>

            <article className={styles.featureCard}>
              <span className={styles.featureKicker}>چندمستأجره</span>
              <h3>جداسازیِ دادهٔ هر کلینیک</h3>
              <p>
                پلتفرم چندمستأجره است و دادهٔ هر کلینیک از دیگری جدا نگه داشته
                می‌شود.
              </p>
            </article>
          </div>
        </section>

        {/* ── Data-trust callout (the differentiator) ── */}
        <section className={styles.trust} aria-labelledby="trust-title">
          <div className={styles.trustInner}>
            <h2 id="trust-title">چرا اعتمادِ داده، تمایزِ ماست</h2>
            <ul className={styles.trustList}>
              <li>
                <strong>دستِ ما به حسابداریِ شما نمی‌رسد</strong>
                اتصال فقط‌خواندنی است؛ این حریمِ کلینیکِ شماست، نه ابزارِ ما.
              </li>
              <li>
                <strong>پزشک تصمیم می‌گیرد، نه سامانه</strong>
                پشتیبانِ تصمیم فقط پیشنهاد می‌دهد؛ پذیرش یا ردِ هر پیشنهاد ثبت
                می‌شود.
              </li>
              <li>
                <strong>هیچ پیامِ بدونِ‌اجازه</strong>
                ارسالِ پیامک به تأییدِ شما و تکمیلِ احرازِ هویت گره خورده است.
              </li>
              <li>
                <strong>عددِ اثبات‌نشده نمی‌سازیم</strong>
                ادعای رشدِ اثبات‌نشده نمی‌کنیم؛ فقط آنچه را که می‌توان نشان داد
                گزارش می‌دهیم.
              </li>
            </ul>
          </div>
        </section>

        {/* ── Demo request ── */}
        <section className={styles.demo} id="demo" aria-labelledby="demo-title">
          <div className={styles.section}>
            <h2 id="demo-title" className={styles.sectionTitle}>
              درخواست دمو
            </h2>
            <p className={styles.sectionLead}>
              برای دیدنِ دموی زنده با دادهٔ نمونه، فرم زیر را پر کنید. با ارسال،
              یک ایمیلِ از پیش‌آماده در برنامهٔ ایمیلِ شما باز می‌شود تا آن را برای
              ما بفرستید.
            </p>

            <div className={styles.demoCard}>
              {/* mailto:-based form — no backend exists yet. Submitting opens
                  the user's mail client with a prefilled message. A real
                  form-backend is a future gate (no fabricated submission). */}
              <form
                action="mailto:hello@halqe.app"
                method="post"
                encType="text/plain"
                aria-label="فرم درخواست دمو"
              >
                <div className={styles.field}>
                  <label htmlFor="demo-name" className={styles.label}>
                    نام و نامِ کلینیک
                  </label>
                  <input
                    id="demo-name"
                    name="name"
                    type="text"
                    className={styles.input}
                    autoComplete="organization"
                    required
                  />
                </div>

                <div className={styles.field}>
                  <label htmlFor="demo-contact" className={styles.label}>
                    راهِ تماس (ایمیل یا تلفن)
                  </label>
                  <input
                    id="demo-contact"
                    name="contact"
                    type="text"
                    className={styles.input}
                    required
                  />
                </div>

                <div className={styles.field}>
                  <label htmlFor="demo-message" className={styles.label}>
                    توضیح (اختیاری)
                  </label>
                  <textarea
                    id="demo-message"
                    name="message"
                    className={styles.textarea}
                  />
                </div>

                <button type="submit" className={styles.btnPrimary}>
                  ارسالِ درخواست
                </button>
              </form>

              <p className={styles.demoNote}>
                توجه: این فرم فعلاً پیامی از طریقِ ایمیلِ شما آماده می‌کند و
                ثبتِ خودکارِ سمتِ سرور ندارد. اگر برنامهٔ ایمیل باز نشد، مستقیماً
                به <a href="mailto:hello@halqe.app">hello@halqe.app</a> بنویسید.
              </p>
            </div>
          </div>
        </section>
      </main>

      {/* ── Footer ── */}
      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <div>
            <div className={styles.footerBrand}>حلقه</div>
            <p className={styles.footerTagline}>
              مدیریتِ بیماری‌های مزمن با احترام به حریمِ دادهٔ کلینیک — پیشنهادِ
              بالینی با تصمیمِ پزشک.
            </p>
          </div>
          <nav className={styles.footerLinks} aria-label="پیوندهای پاورقی">
            <Link href="/login">ورود به پنل</Link>
            <a href="#demo">درخواست دمو</a>
          </nav>
        </div>
      </footer>
    </div>
  );
}
