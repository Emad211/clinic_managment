/**
 * SwRegistrar — ثبتِ Service Worker در client
 *
 * یک client component سبک که فقط برای ثبتِ SW از سمتِ مرورگر است.
 * به‌خاطرِ اینکه SW نیاز به window دارد، باید "use client" باشد.
 * هیچ UI رندر نمی‌کند.
 */

"use client";

import { useEffect } from "react";

export function SwRegistrar() {
  useEffect(() => {
    if (
      typeof window !== "undefined" &&
      "serviceWorker" in navigator
    ) {
      navigator.serviceWorker
        .register("/sw.js", { scope: "/" })
        .catch(() => {
          // SW registration failure is non-critical — silently ignored.
          // App still works without a SW (online-first fallback).
        });
    }
  }, []);

  return null;
}
