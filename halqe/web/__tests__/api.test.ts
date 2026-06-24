/**
 * Unit tests for the API client lib (src/lib/api.ts).
 * Uses a mocked fetch — no real network calls.
 */

// Mock localStorage
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

import { saveToken, getToken, clearToken, ApiError } from "../src/lib/api";

// ────────────────────────────────────────────────────────────
// Token helpers
// ────────────────────────────────────────────────────────────

describe("token storage", () => {
  beforeEach(() => localStorageMock.clear());

  test("getToken returns null when nothing is stored", () => {
    expect(getToken()).toBeNull();
  });

  test("saveToken + getToken round-trips correctly", () => {
    saveToken("test-jwt-token-abc123");
    expect(getToken()).toBe("test-jwt-token-abc123");
  });

  test("clearToken removes the token", () => {
    saveToken("some-token");
    clearToken();
    expect(getToken()).toBeNull();
  });
});

// ────────────────────────────────────────────────────────────
// apiLogin — fetch mock
// ────────────────────────────────────────────────────────────

describe("apiLogin", () => {
  beforeEach(() => {
    localStorageMock.clear();
    jest.resetAllMocks();
  });

  test("returns token on 200", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ token: "eyJhbGciOiJIUzI1NiJ9.test" }),
    }) as jest.Mock;

    // Import dynamically so fetch mock is in place
    const { apiLogin } = await import("../src/lib/api");
    const result = await apiLogin("admin", "admin");
    expect(result.token).toBe("eyJhbGciOiJIUzI1NiJ9.test");
  });

  test("throws ApiError with status 401 on wrong credentials", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      json: async () => ({ detail: "Invalid credentials" }),
    }) as jest.Mock;

    const { apiLogin } = await import("../src/lib/api");
    await expect(apiLogin("bad", "creds")).rejects.toBeInstanceOf(ApiError);
    await expect(apiLogin("bad", "creds")).rejects.toMatchObject({
      status: 401,
    });
  });
});

// ────────────────────────────────────────────────────────────
// apiGetPatients — fetch mock
// ────────────────────────────────────────────────────────────

describe("apiGetPatients", () => {
  beforeEach(() => {
    localStorageMock.clear();
    jest.resetAllMocks();
    saveToken("mock-bearer-token");
  });

  test("returns patient list on 200", async () => {
    const mockPayload = {
      items: [
        {
          link_id: 1,
          patient_id: 1,
          is_active: true,
          enrolled_at: "2024-06-01T10:00:00+03:30",
          full_name: "نمونه ۱ - کنترل خوب",
          national_id: "TEST0001",
          phone_number: "09120000001",
          patient_uuid: "abc-123",
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
    };

    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => mockPayload,
    }) as jest.Mock;

    const { apiGetPatients } = await import("../src/lib/api");
    const result = await apiGetPatients(20, 0);
    expect(result.total).toBe(1);
    expect(result.items[0].national_id).toBe("TEST0001");
    expect(result.items[0].full_name).toBe("نمونه ۱ - کنترل خوب");
  });

  test("attaches Authorization header with Bearer token", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 20, offset: 0 }),
    }) as jest.Mock;

    const { apiGetPatients } = await import("../src/lib/api");
    await apiGetPatients();

    const callArgs = (globalThis.fetch as jest.Mock).mock.calls[0];
    const headers = callArgs[1]?.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer mock-bearer-token");
  });
});
