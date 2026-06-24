import { redirect } from "next/navigation";

/**
 * Root page — redirect to /patients (authenticated) or /login.
 * The redirect target is /patients; middleware or the patients page
 * itself redirects to /login when no token is present.
 */
export default function Home() {
  redirect("/patients");
}
