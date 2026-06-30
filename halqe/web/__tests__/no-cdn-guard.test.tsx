/**
 * Regression Guard — no-cdn-guard.test.tsx
 *
 * Enforces the "offline by design / no external CDN" sacred constraint at the
 * SOURCE level, plus the RTL/lang baseline of the root layout.
 *
 * ── What this is ──────────────────────────────────────────────────────────
 * This is a SOURCE-SCAN guard, not a build/runtime check. It greps the actual
 * source files (ts / tsx / css under src) for the syntactic ways a page would
 * pull a remote asset: a <script src="https…">, a <link href="https…">, a
 * `next/font/google` import, an `@import url(https…)`, an `@font-face` src
 * pointing at a remote URL, a remote `import … from "https…"`, or a
 * `fetch("https…")`.
 *
 * ── What this is NOT ──────────────────────────────────────────────────────
 * It does NOT catch an npm dependency that, at runtime, opens a connection to a
 * CDN (e.g. a bundled library that lazy-loads from the network). That is a
 * different defense layer — a Content-Security-Policy header and/or a build-time
 * network-isolation check own that risk. This guard owns the *authored source*.
 *
 * ── False-positive defenses (why this is not flaky) ───────────────────────
 *  1. Comments are stripped FIRST (JS/TS block + line, CSS block) so that the
 *     `http://127.0.0.1` documentation comments in src/lib/api.ts and
 *     src/lib/api/_core.ts, and a `// see next/font/google docs` note, never
 *     register as violations.
 *  2. Patterns are CONTEXT-BOUND, not "any https". A metadata canonical
 *     (`new URL("https://halqe.app")`), a JSON-LD `"@context":"https://schema.org"`,
 *     and an `og:url` string are plain string literals — none match a
 *     <script>/<link>/@import/import-from/fetch context, so no host allowlist is
 *     needed.
 *  3. Paths are normalized to forward slashes (win32) and anything under a
 *     `__tests__/` directory (or a *.test.* file, or this guard itself) is
 *     excluded — so test fixtures that mention remote URLs in comments don't
 *     trip the scan.
 *
 * Header/style modeled on __tests__/suggestions-guard.test.tsx.
 */

import * as fs from "fs";
import * as path from "path";

// ─────────────────────────────────────────────────────────────
// Pure detector — exported for the self-test layer
// ─────────────────────────────────────────────────────────────

/** A single offline-violation hit. */
export interface CdnViolation {
  file: string;
  line: number;
  pattern: string;
}

/**
 * Strip comments from source so URL-bearing comments never count as violations.
 * Handles JS/TS line and block comments plus CSS block comments (CSS has no
 * line comments). Replaces stripped spans with spaces of equal length so
 * 1-based line numbers stay correct.
 */
function stripComments(content: string): string {
  let out = "";
  let i = 0;
  const n = content.length;
  // States: 0 = code, 1 = line comment, 2 = block comment,
  //         3 = single-quote str, 4 = double-quote str, 5 = template str
  let state = 0;

  while (i < n) {
    const c = content[i];
    const c2 = i + 1 < n ? content[i + 1] : "";

    if (state === 0) {
      if (c === "/" && c2 === "/") {
        state = 1;
        out += "  ";
        i += 2;
        continue;
      }
      if (c === "/" && c2 === "*") {
        state = 2;
        out += "  ";
        i += 2;
        continue;
      }
      if (c === "'") {
        state = 3;
        out += c;
        i += 1;
        continue;
      }
      if (c === '"') {
        state = 4;
        out += c;
        i += 1;
        continue;
      }
      if (c === "`") {
        state = 5;
        out += c;
        i += 1;
        continue;
      }
      out += c;
      i += 1;
      continue;
    }

    if (state === 1) {
      // line comment — keep newlines, blank everything else
      if (c === "\n") {
        state = 0;
        out += c;
      } else {
        out += " ";
      }
      i += 1;
      continue;
    }

    if (state === 2) {
      // block comment — keep newlines so line numbers are preserved
      if (c === "*" && c2 === "/") {
        state = 0;
        out += "  ";
        i += 2;
      } else {
        out += c === "\n" ? "\n" : " ";
        i += 1;
      }
      continue;
    }

    // string states (3/4/5): copy verbatim, honor escapes, exit on matching quote
    if (state === 3 || state === 4 || state === 5) {
      if (c === "\\") {
        out += c + (c2 || "");
        i += 2;
        continue;
      }
      const quote = state === 3 ? "'" : state === 4 ? '"' : "`";
      if (c === quote) {
        state = 0;
      }
      out += c;
      i += 1;
      continue;
    }
  }

  return out;
}

/**
 * Violation patterns — each is CONTEXT-BOUND so plain string literals
 * (metadata canonicals, JSON-LD @context, og:url) are NOT flagged.
 */
const VIOLATION_PATTERNS: { name: string; re: RegExp }[] = [
  // <script … src="https://…"> or protocol-relative //host
  {
    name: "remote <script src>",
    re: /<script[^>]*\bsrc\s*=\s*["'](?:https?:|\/\/)/i,
  },
  // <link … href="https://…"> (any rel — preconnect/stylesheet/etc.)
  {
    name: "remote <link href>",
    re: /<link[^>]*\bhref\s*=\s*["'](?:https?:|\/\/)/i,
  },
  // import { … } from "next/font/google"  (the Google-font loader — banned)
  {
    name: "next/font/google import",
    re: /from\s+["']next\/font\/google["']/,
  },
  // CSS @import url(https://…) or @import "https://…"
  {
    name: "@import remote",
    re: /@import\s+(?:url\(\s*)?["']?https?:/i,
  },
  // @font-face { src: url(https://…) }
  {
    name: "@font-face remote src",
    re: /\bsrc\s*:\s*url\(\s*["']?https?:/i,
  },
  // import … from "https://…"   (remote ESM)
  {
    name: "remote import-from",
    re: /\bimport\b[^;]*\bfrom\s+["']https?:/i,
  },
  // dynamic import("https://…")
  {
    name: "remote dynamic import()",
    re: /\bimport\(\s*["']https?:/i,
  },
  // fetch("https://…")
  {
    name: "remote fetch()",
    re: /\bfetch\(\s*["']https?:/i,
  },
];

/**
 * Scan a single file's content for offline/no-CDN violations.
 * PURE — takes path + content, returns hits. Strips comments first.
 */
export function scanForViolations(
  filePath: string,
  content: string,
): CdnViolation[] {
  const file = filePath.replace(/\\/g, "/");
  const stripped = stripComments(content);
  const lines = stripped.split("\n");
  const hits: CdnViolation[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    for (const { name, re } of VIOLATION_PATTERNS) {
      if (re.test(line)) {
        hits.push({ file, line: i + 1, pattern: name });
      }
    }
  }
  return hits;
}

// ─────────────────────────────────────────────────────────────
// File-system walk (manual, recursive) over real source
// ─────────────────────────────────────────────────────────────

const SRC_ROOT = path.join(__dirname, "..", "src");
const SCAN_EXTS = new Set([".ts", ".tsx", ".css"]);

/** True if a normalized path is a test file/dir or the guard itself. */
function isExcluded(normalized: string): boolean {
  return (
    normalized.includes("/__tests__/") ||
    /\.test\.tsx?$/.test(normalized) ||
    normalized.endsWith("/no-cdn-guard.test.tsx")
  );
}

/** Recursively collect scannable source files under SRC_ROOT. */
function collectSourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    const normalized = full.replace(/\\/g, "/");
    if (entry.isDirectory()) {
      if (entry.name === "node_modules") continue;
      out.push(...collectSourceFiles(full));
    } else if (SCAN_EXTS.has(path.extname(entry.name))) {
      if (isExcluded(normalized)) continue;
      out.push(full);
    }
  }
  return out;
}

// ─────────────────────────────────────────────────────────────
// Layer 1 — self-test the detector on inline samples (mutation-proof)
// ─────────────────────────────────────────────────────────────

describe("scanForViolations — detector self-test (positive samples)", () => {
  it("flags a remote <script src>", () => {
    const hits = scanForViolations(
      "x.tsx",
      '<script src="https://cdn.x/a.js"></script>',
    );
    expect(hits).toHaveLength(1);
    expect(hits[0].pattern).toBe("remote <script src>");
  });

  it("flags a protocol-relative <script src>", () => {
    const hits = scanForViolations("x.tsx", '<script src="//cdn.x/a.js">');
    expect(hits).toHaveLength(1);
  });

  it("flags a remote <link href> (any rel)", () => {
    const hits = scanForViolations(
      "x.tsx",
      '<link rel="preconnect" href="https://fonts.googleapis.com">',
    );
    expect(hits).toHaveLength(1);
    expect(hits[0].pattern).toBe("remote <link href>");
  });

  it("flags a next/font/google import", () => {
    const hits = scanForViolations(
      "x.tsx",
      'import { Vazirmatn } from "next/font/google";',
    );
    expect(hits).toHaveLength(1);
    expect(hits[0].pattern).toBe("next/font/google import");
  });

  it("flags a CSS @import of a remote URL", () => {
    const hits = scanForViolations(
      "x.css",
      '@import url("https://fonts.googleapis.com/css?family=Roboto");',
    );
    expect(hits).toHaveLength(1);
    expect(hits[0].pattern).toBe("@import remote");
  });

  it("flags an @font-face remote src", () => {
    const hits = scanForViolations(
      "x.css",
      '@font-face{src:url("https://fonts.gstatic.com/x.woff2")}',
    );
    expect(hits).toHaveLength(1);
    expect(hits[0].pattern).toBe("@font-face remote src");
  });

  it("flags a remote import-from", () => {
    const hits = scanForViolations(
      "x.tsx",
      'import confetti from "https://esm.sh/canvas-confetti";',
    );
    expect(hits).toHaveLength(1);
    expect(hits[0].pattern).toBe("remote import-from");
  });

  it("flags a remote dynamic import()", () => {
    const hits = scanForViolations(
      "x.tsx",
      'const m = await import("https://esm.sh/x");',
    );
    expect(hits).toHaveLength(1);
    expect(hits[0].pattern).toBe("remote dynamic import()");
  });

  it("flags a remote fetch()", () => {
    const hits = scanForViolations(
      "x.tsx",
      'fetch("https://api.evil.example/track")',
    );
    expect(hits).toHaveLength(1);
    expect(hits[0].pattern).toBe("remote fetch()");
  });
});

describe("scanForViolations — detector self-test (negative samples)", () => {
  it("does NOT flag a JSON-LD @context string literal", () => {
    const hits = scanForViolations("x.tsx", '"@context":"https://schema.org",');
    expect(hits).toHaveLength(0);
  });

  it("does NOT flag a metadata canonical new URL()", () => {
    const hits = scanForViolations(
      "x.tsx",
      'metadataBase: new URL("https://halqe.app"),',
    );
    expect(hits).toHaveLength(0);
  });

  it("does NOT flag a local @font-face src", () => {
    const hits = scanForViolations(
      "x.css",
      'src: url("/fonts/Vazirmatn-Bold.woff2") format("woff2");',
    );
    expect(hits).toHaveLength(0);
  });

  it("does NOT flag next/font/local", () => {
    const hits = scanForViolations(
      "x.tsx",
      'import localFont from "next/font/local";',
    );
    expect(hits).toHaveLength(0);
  });

  it("does NOT flag a URL that lives in a // line comment (strip proof)", () => {
    const hits = scanForViolations(
      "x.tsx",
      '// see next/font/google docs and http://127.0.0.1:8099/api',
    );
    expect(hits).toHaveLength(0);
  });

  it("does NOT flag a URL inside a /* block comment */ (strip proof)", () => {
    const hits = scanForViolations(
      "x.ts",
      '/* dev uses http://127.0.0.1:8099 and <script src="https://x"> */ const a = 1;',
    );
    expect(hits).toHaveLength(0);
  });

  it("does NOT flag a same-origin relative fetch", () => {
    const hits = scanForViolations("x.tsx", 'fetch("/api/v1/patients")');
    expect(hits).toHaveLength(0);
  });

  it("does NOT flag an og:url / siteName string literal", () => {
    const hits = scanForViolations("x.tsx", 'url: "https://halqe.app",');
    expect(hits).toHaveLength(0);
  });
});

// ─────────────────────────────────────────────────────────────
// Layer 2 — full scan of real source files must be clean today
// ─────────────────────────────────────────────────────────────

describe("no-CDN full source scan (offline by design)", () => {
  it("src/**/*.{ts,tsx,css} contains zero remote-asset violations", () => {
    const files = collectSourceFiles(SRC_ROOT);
    // Sanity: the walk actually found source (guards against a broken path).
    expect(files.length).toBeGreaterThan(0);

    const allHits: CdnViolation[] = [];
    for (const f of files) {
      const content = fs.readFileSync(f, "utf8");
      allHits.push(...scanForViolations(f, content));
    }

    // If this fails, DO NOT silence it — a real remote asset was introduced.
    // Throw a readable report FIRST (so the listing is visible), then assert.
    if (allHits.length) {
      const report = allHits
        .map((h) => `  ${h.file}:${h.line} → ${h.pattern}`)
        .join("\n");
      throw new Error(`Remote-asset violations:\n${report}`);
    }
    expect(allHits).toEqual([]);
  });
});

// ─────────────────────────────────────────────────────────────
// Layer 3 — the local Vazirmatn fonts referenced by globals.css exist
// (so the local @font-face srcs do not 404 → no silent CDN fallback)
// ─────────────────────────────────────────────────────────────

describe("local Vazirmatn fonts are present (no 404 → no CDN fallback)", () => {
  const FONT_DIR = path.join(__dirname, "..", "public", "fonts");
  const FONTS = [
    "Vazirmatn-Regular.woff2",
    "Vazirmatn-Medium.woff2",
    "Vazirmatn-SemiBold.woff2",
    "Vazirmatn-Bold.woff2",
  ];

  it.each(FONTS)("public/fonts/%s exists", (name) => {
    expect(fs.existsSync(path.join(FONT_DIR, name))).toBe(true);
  });
});

// ─────────────────────────────────────────────────────────────
// RTL / lang baseline — the root layout declares Persian + RTL
// (RRTL/Jalali has no other gap per the U5 audit — assert only this)
// ─────────────────────────────────────────────────────────────

describe("root layout RTL/lang baseline", () => {
  const layoutSrc = fs.readFileSync(
    path.join(__dirname, "..", "src", "app", "layout.tsx"),
    "utf8",
  );

  it("renders <html lang=\"fa\" dir=\"rtl\">", () => {
    // Tolerant of attribute order/whitespace, strict on both values.
    expect(layoutSrc).toMatch(
      /<html(?=[^>]*\blang\s*=\s*["']fa["'])(?=[^>]*\bdir\s*=\s*["']rtl["'])[^>]*>/,
    );
  });
});
