/**
 * useAuth — centralized auth guard hook.
 *
 * Usage (in any "use client" page):
 *   const { ready } = useAuth();
 *   if (!ready) return null; // or a spinner
 *
 * On mount it checks for a valid (non-expired) JWT via getToken().
 * If the token is absent or expired it redirects to /login immediately.
 * Returns `ready: true` only once we have confirmed a valid token exists,
 * so the page can render without a flash of unauthenticated content.
 *
 * Also exposes `logout()` so pages don't need to import clearToken directly.
 */

"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { getToken, clearToken } from "@/lib/api";

interface UseAuthReturn {
  /** True once a valid token is confirmed — use as render gate. */
  ready: boolean;
  /** Call to clear the token and redirect to /login. */
  logout: () => void;
}

export function useAuth(): UseAuthReturn {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  const logout = useCallback(() => {
    clearToken();
    router.push("/login");
  }, [router]);

  useEffect(() => {
    // getToken() already evicts expired tokens and returns null
    if (!getToken()) {
      router.push("/login");
      return;
    }
    setReady(true);
  }, [router]);

  return { ready, logout };
}
