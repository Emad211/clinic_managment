import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "حلقه — پلتفرم مدیریت بیماری‌های مزمن",
  description: "سامانهٔ هوشمند مراقبت از بیماران مزمن — حلقهٔ مراقبت",
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
          Google Fonts is avoided (offline-first).
          Vazirmatn is the recommended Persian font but must be vendored in a
          future slice. The CSS stack falls back to system fonts for now.
        */}
      </head>
      <body>{children}</body>
    </html>
  );
}
