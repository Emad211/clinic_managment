/**
 * Architecture Guard — control-room.test.tsx
 *
 * The control-room page is a READ-ONLY triage surface. This guard enforces
 * "zero state-writes" at the client layer:
 *
 *   1. Every exported function in src/lib/api/control-room issues a GET
 *      (no explicit method, or method === "GET") — never POST/PUT/PATCH/DELETE.
 *   2. Completeness: the set of exported FUNCTIONS exactly equals the set we
 *      have covered here — so a future write-function cannot slip in unguarded.
 *
 * Pattern mirrors api.test.ts (localStorageMock + saveToken + dynamic import)
 * and suggestions-guard.test.tsx (architecture-guard intent).
 */

// ── Mock localStorage (same shape as api.test.ts) ──
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();

Object.defineProperty(globalThis, "localStorage", {
  value: localStorageMock,
});

import { saveToken } from "../src/lib/api";

// A minimal panel/conversion payload — shape is irrelevant to the guard; we
// only assert on the request method, not the response.
const PAYLOAD = {
  patients: [],
  cohorts: [],
  median_rev: 0,
  total: 0,
  show_value: false,
  // conversion fields (so a single payload works for every GET)
  window_days: 30,
  generated: 0,
  generated_eligible: 0,
  resolved_done: 0,
  resolved_dismissed: 0,
  open_eligible: 0,
  to_visit: 0,
  contact_rate: null,
  visit_rate_of_reached: null,
  overall_conversion: null,
  n_sufficient: false,
  framing: "بدونِ گروهِ کنترل",
  cohort_key: "uncontrolled",
  ids: [],
  count: 0,
};

beforeEach(() => {
  localStorageMock.clear();
  jest.resetAllMocks();
  saveToken("mock-bearer-token");
  globalThis.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => PAYLOAD,
  }) as jest.Mock;
});

// The functions we KNOW about and assert are GET-only.
const COVERED = ["apiGetControlRoom", "apiGetConversion", "apiGetCohortIds"] as const;

function methodOf(call: unknown[]): string {
  const opts = call[1] as RequestInit | undefined;
  return (opts?.method ?? "GET").toString().toUpperCase();
}

describe("control-room API client — read-only guard", () => {
  test("apiGetControlRoom issues a GET", async () => {
    const mod = await import("../src/lib/api/control-room");
    await mod.apiGetControlRoom();
    const calls = (globalThis.fetch as jest.Mock).mock.calls;
    expect(calls).toHaveLength(1);
    expect(methodOf(calls[0])).toBe("GET");
    expect(String(calls[0][0])).toContain("/control-room");
  });

  test("apiGetConversion issues a GET", async () => {
    const mod = await import("../src/lib/api/control-room");
    await mod.apiGetConversion();
    const calls = (globalThis.fetch as jest.Mock).mock.calls;
    expect(methodOf(calls[0])).toBe("GET");
    expect(String(calls[0][0])).toContain("/control-room/conversion");
  });

  test("apiGetCohortIds issues a GET and encodes the key in the path", async () => {
    const mod = await import("../src/lib/api/control-room");
    await mod.apiGetCohortIds("uncontrolled_lapsed");
    const calls = (globalThis.fetch as jest.Mock).mock.calls;
    expect(methodOf(calls[0])).toBe("GET");
    expect(String(calls[0][0])).toContain("/control-room/cohort/uncontrolled_lapsed");
  });

  test("EVERY exported function issues only GET (no POST/PUT/PATCH/DELETE)", async () => {
    const mod = await import("../src/lib/api/control-room");
    const fns = Object.entries(mod).filter(
      ([, v]) => typeof v === "function",
    ) as [string, (...a: unknown[]) => Promise<unknown>][];

    for (const [name, fn] of fns) {
      (globalThis.fetch as jest.Mock).mockClear();
      // Call with a dummy string arg — functions that ignore extra args are fine.
      await fn("uncontrolled");
      const calls = (globalThis.fetch as jest.Mock).mock.calls;
      expect(calls.length).toBeGreaterThan(0);
      for (const call of calls) {
        expect(methodOf(call)).toBe("GET");
      }
      // Belt-and-suspenders: explicitly reject mutation verbs.
      for (const call of calls) {
        const m = methodOf(call);
        expect(["POST", "PUT", "PATCH", "DELETE"]).not.toContain(m);
      }
      // name is referenced so eslint no-unused stays quiet and failures name the fn
      expect(typeof name).toBe("string");
    }
  });

  test("completeness: exported functions exactly equal the covered set", async () => {
    const mod = await import("../src/lib/api/control-room");
    const exportedFns = Object.entries(mod)
      .filter(([, v]) => typeof v === "function")
      .map(([k]) => k)
      .sort();
    // If a new function is added to control-room.ts, this test fails until it
    // is added to COVERED above (forcing a deliberate read-only review).
    expect(exportedFns).toEqual([...COVERED].sort());
  });
});
