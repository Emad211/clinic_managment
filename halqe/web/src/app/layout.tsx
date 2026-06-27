import type { Metadata } from "next";
import "./globals.css";
import { SwRegistrar } from "@/components/SwRegistrar";

export const metadata: Metadata = {
  // metadataBase makes OG/canonical URLs absolute. Overridable later via env;
  // a sensible default so sitemap/robots/OG resolve correctly in the build.
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL ?? "https://halqe.app",
  ),
  title: "حلقه — پلتفرم مدیریت بیماری‌های مزمن",
  description:
    "حلقه بیمارانِ مزمنِ در حالِ ریزش را شناسایی و بازمی‌گرداند — پرونده فقط‌خواندنی از حسابداری، پیشنهادِ بالینیِ مبتنی بر گایدلاین با تصمیمِ پزشک، و پیامک فقط با اجازهٔ کلینیک.",
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
  manifest: "/manifest.json",
  openGraph: {
    title: "حلقه — پلتفرم مدیریت بیماری‌های مزمن",
    description:
      "شناسایی و بازگرداندنِ بیمارانِ مزمن، با پرونده‌ای فقط‌خواندنی از حسابداری و پیشنهادِ بالینی که تصمیمش با پزشک است.",
    type: "website",
    locale: "fa_IR",
    siteName: "حلقه",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fa" dir="rtl">
      <head>
        {/*
          Vazirmatn is vendored in public/fonts/ — @font-face in globals.css.
          No external CDN. manifest.json is declared via metadata above
          (Next.js injects the <link rel="manifest"> automatically).
        */}
      </head>
      <body>
        <SwRegistrar />
        {children}
      </body>
    </html>
  );
}
