import { API_URL, appCheckToken, authToken } from "../api/ClientProvider";

export const endpoint = (path: string) => `${API_URL?.replace(/\/$/, "") ?? ""}${path}`;

export async function signedAppFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = await authToken?.();
  const appCheck = await appCheckToken?.();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (appCheck) headers.set("X-Firebase-AppCheck", appCheck);
  return fetch(endpoint(path), { ...init, headers, credentials: "omit" });
}
