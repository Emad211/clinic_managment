"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { apiLogin, saveToken, ApiError } from "@/lib/api";
import styles from "./login.module.css";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const { token } = await apiLogin(username, password);
      saveToken(token);
      router.push("/dashboard");
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          setError("نام کاربری یا رمز عبور اشتباه است.");
        } else if (err.status === 423) {
          setError("حساب کاربری قفل شده است. لطفاً ۱۵ دقیقه بعد تلاش کنید.");
        } else {
          setError(`خطای سرور (${err.status}): ${err.message}`);
        }
      } else {
        setError("اتصال به سرور برقرار نشد.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className={styles.container}>
      <div className={styles.card}>
        {/* Brand header */}
        <header className={styles.header}>
          <h1 className={styles.brand}>حلقه</h1>
          <p className={styles.subtitle}>پلتفرم مدیریت بیماری‌های مزمن</p>
        </header>

        <form onSubmit={handleSubmit} noValidate aria-label="فرم ورود">
          <div className={styles.field}>
            <label htmlFor="username" className={styles.label}>
              نام کاربری
            </label>
            <input
              id="username"
              name="username"
              type="text"
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className={styles.input}
              placeholder="admin"
              aria-required="true"
              disabled={loading}
            />
          </div>

          <div className={styles.field}>
            <label htmlFor="password" className={styles.label}>
              رمز عبور
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={styles.input}
              placeholder="••••••••"
              aria-required="true"
              disabled={loading}
            />
          </div>

          {error && (
            <div role="alert" className={styles.error}>
              {error}
            </div>
          )}

          <button
            type="submit"
            className={styles.button}
            disabled={loading || !username || !password}
            aria-busy={loading}
          >
            {loading ? "در حال ورود…" : "ورود به سامانه"}
          </button>
        </form>
      </div>
    </main>
  );
}
