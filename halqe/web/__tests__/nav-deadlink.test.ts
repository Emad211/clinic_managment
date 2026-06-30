/**
 * Nav dead-link guard (step 86, U3).
 *
 * Every STATIC href in NAV_LINKS + MANAGER_LINKS must map to a real App-Router
 * page file `src/app/<href>/page.tsx`. This is the structural defence against
 * shipping a nav link to a route that does not exist (e.g. /clinic-setup or
 * /intake, which are NOT built).
 *
 * Pure fs check — Nav's runtime deps (next/link, @/lib/api, css) are stubbed so
 * the module imports cleanly in node without a DOM.
 */

import fs from "fs";
import path from "path";

// Stub Nav's runtime imports so importing the module is side-effect-free.
jest.mock("@/lib/api", () => ({ getRole: () => null }));
jest.mock("next/link", () => "a");
jest.mock("@/components/nav.module.css", () => ({}), { virtual: true });

import { NAV_LINKS, MANAGER_LINKS } from "@/components/Nav";

// jest runs with cwd = web/ (next/jest dir: "./").
const APP_DIR = path.join(process.cwd(), "src", "app");

/** Resolve a static href like "/manager/outcomes" to its page.tsx path. */
function pageFileFor(href: string): string {
  const rel = href.replace(/^\//, "");
  return path.join(APP_DIR, rel, "page.tsx");
}

describe("Nav dead-link guard", () => {
  const allLinks = [...NAV_LINKS, ...MANAGER_LINKS];

  it.each(allLinks)("link %p resolves to a real page.tsx", (link) => {
    // Only static hrefs (no dynamic [param]) are checked.
    expect(link.href.includes("[")).toBe(false);
    const file = pageFileFor(link.href);
    expect(fs.existsSync(file)).toBe(true);
  });

  it("control-room is in the manager group, not the universal links", () => {
    expect(NAV_LINKS.some((l) => l.href === "/control-room")).toBe(false);
    expect(MANAGER_LINKS.some((l) => l.href === "/control-room")).toBe(true);
  });
});
