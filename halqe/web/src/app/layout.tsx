import type { Metadata } from "next";
import "./globals.css";
import { SwRegistrar } from "@/components/SwRegistrar";

export const metadata: Metadata = {
  title: "حلقه — پلتفرم مدیریت بیماری‌های مزمن",
  description: "سامانهٔ هوشمند مراقبت از بیماران مزمن — حلقهٔ مراقبت",
  manifest: "/manifest.json",
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
