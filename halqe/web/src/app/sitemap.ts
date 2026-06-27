import type { MetadataRoute } from "next";

/**
 * Sitemap for the public surface of «حلقه».
 *
 * Only the public marketing landing ("/") is indexable. Every app route
 * (/dashboard, /patients, /worklist, /manager, /card, /report, /queue, /login)
 * is private/authenticated and is intentionally excluded here (and disallowed
 * in robots.ts).
 */
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://halqe.app";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: `${SITE_URL}/`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 1,
    },
  ];
}
