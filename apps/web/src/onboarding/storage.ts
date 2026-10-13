// ONBOARD-1: "seen" is remembered per person in this browser's localStorage, never sent anywhere. Every read and
// write is in try/catch: a blocked or missing store means the welcome may show again, never a crash.
import type { AuthState } from "../auth/auth";

const PREFIX = "tilo.onboarding.v1.";

/** One key per person: the Google account's email, the anonymous demo session, or the local demo (no sign-in). */
export function userKeyOf(state: AuthState): string {
  if (state.status === "google") {
    const who = (state.email ?? "").trim().toLowerCase();
    return `google:${who || "account"}`;
  }
  return state.status === "anonymous" ? "anonymous" : "demo";
}

function store(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function hasSeen(key: string): boolean {
  try {
    return store()?.getItem(PREFIX + key) != null;
  } catch {
    return false;
  }
}

export function markSeen(key: string): void {
  try {
    store()?.setItem(PREFIX + key, "seen");
  } catch {
    // storage blocked or full: the welcome may show again on the next visit, nothing else
  }
}
