/**
 * Auth domain — login.
 */
import { apiFetch } from "./_core";

export interface LoginResponse {
  token: string;
}

export async function apiLogin(
  username: string,
  password: string,
): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}
