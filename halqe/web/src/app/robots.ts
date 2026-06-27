import type { MetadataRoute } from "next";

/**
 * robots.txt for «حلقه».
 *
 * Allow the public landing ("/"); disallow every authenticated app route from
 * indexing — these are private and behind a login, so they should never appear
 * in search results.
 */
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://halqe.app";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: [
        "/dashboard",
        "/patients",
        "/worklist",
        "/manager",
        "/card",
        "/report",
        "/queue",
        "/login",
      ],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
