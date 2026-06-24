import { redirect } from "next/navigation";

/**
 * Root page — redirect authenticated users to /dashboard, unauthenticated to /login.
 * Token checking at the server level isn't available here (localStorage is client-only),
 * so we redirect to /dashboard which performs its own client-side auth guard and
 * bounces to /login when no token is present.
 */
export default function Home() {
  redirect("/dashboard");
}
