// The composer's Quick / Thinking choice, remembered per person (COST-FAST-1). Kept in this browser only:
// `localStorage` keyed by a hash of the signed-in email (never the address itself: a shared machine must not list who used Tilo, BQ-SIGNIN-4;
// sign-out also clears every key, api/signOut.ts), with an in-memory
// fallback for when storage is absent or throws (private mode, blocked site data). Thinking is the default: it is
// what every start has been, so nothing changes for a person who never chooses.
import type { Effort } from "../../api/types";

export const DEFAULT_EFFORT: Effort = "thinking";

const PREFIX = "tilo.park.effort.";
/** The signed-in email is not known until the user read lands; until then the choice is the device's. */
const ANON = "anonymous";

/** In-memory fallback, per key, for the life of the page: only what storage refused to keep (or could not be read). */
const memory = new Map<string, Effort>();

/** Two 32-bit FNV-1a passes with different offsets: a short stable name for the email, not a secret. */
function hashOf(text: string): string {
  let a = 0x811c9dc5;
  let b = 0x9747b28c;
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    a = Math.imul(a ^ c, 0x01000193);
    b = Math.imul(b ^ c, 0x01000193);
  }
  return (a >>> 0).toString(16).padStart(8, "0") + (b >>> 0).toString(16).padStart(8, "0");
}

const keyOf = (email: string | null | undefined): string =>
  `${PREFIX}${email ? hashOf(email.trim().toLowerCase()) : ANON}`;

const isEffort = (v: unknown): v is Effort => v === "quick" || v === "thinking";

export function readEffort(email?: string | null): Effort {
  const key = keyOf(email);
  try {
    const stored = window.localStorage.getItem(key);
    if (isEffort(stored)) return stored;
  } catch {
    // storage absent or blocked: the in-memory value below
  }
  return memory.get(key) ?? DEFAULT_EFFORT;
}

export function writeEffort(email: string | null | undefined, effort: Effort): void {
  const key = keyOf(email);
  try {
    window.localStorage.setItem(key, effort);
    memory.delete(key);
  } catch {
    memory.set(key, effort); // storage would not keep it: remembered for this page only
  }
}
