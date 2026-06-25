/**
 * Unit tests for src/lib/vital-level.ts
 *
 * Tests the pure mapping function vitalLevelDisplay — no React, no DOM.
 */

import { vitalLevelDisplay } from "../vital-level";

describe("vitalLevelDisplay", () => {
  it("maps 'danger' to key=danger, non-empty label and ariaLabel", () => {
    const result = vitalLevelDisplay("danger");
    expect(result.key).toBe("danger");
    expect(result.label).toBeTruthy();
    expect(result.label).toContain("خطر");
    expect(result.ariaLabel).toBeTruthy();
    expect(result.ariaLabel).toContain("خطر");
  });

  it("maps 'warn' to key=warn, non-empty label and ariaLabel", () => {
    const result = vitalLevelDisplay("warn");
    expect(result.key).toBe("warn");
    expect(result.label).toBeTruthy();
    expect(result.label).toContain("احتیاط");
    expect(result.ariaLabel).toBeTruthy();
  });

  it("maps 'ok' to key=ok, non-empty label and ariaLabel", () => {
    const result = vitalLevelDisplay("ok");
    expect(result.key).toBe("ok");
    expect(result.label).toBeTruthy();
    expect(result.label).toContain("عادی");
    expect(result.ariaLabel).toBeTruthy();
  });

  it("maps null to key=none, empty label and ariaLabel", () => {
    const result = vitalLevelDisplay(null);
    expect(result.key).toBe("none");
    expect(result.label).toBe("");
    expect(result.ariaLabel).toBe("");
  });

  it("maps undefined to key=none, empty label and ariaLabel", () => {
    const result = vitalLevelDisplay(undefined);
    expect(result.key).toBe("none");
    expect(result.label).toBe("");
    expect(result.ariaLabel).toBe("");
  });

  it("returns different keys for ok vs warn vs danger", () => {
    const keys = ["ok", "warn", "danger"].map(
      (l) => vitalLevelDisplay(l as "ok" | "warn" | "danger").key,
    );
    expect(new Set(keys).size).toBe(3);
  });
});
