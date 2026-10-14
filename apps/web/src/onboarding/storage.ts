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

const SILENCED = `${PREFIX}silenced.`;

/** QA row 22: "Not now" on one page's invitation silences every page's invitation for this browser session
 * (sessionStorage: a reload is the same session; the next visit asks again). Never sent anywhere. */
export function silenceInvitations(userKey: string): void {
  try {
    window.sessionStorage.setItem(SILENCED + userKey, "1");
  } catch {
    // blocked: the next page may ask once more, nothing else
  }
}

export function invitationsSilenced(userKey: string): boolean {
  try {
    return window.sessionStorage.getItem(SILENCED + userKey) != null;
  } catch {
    return false;
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
