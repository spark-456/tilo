// The composer's Quick / Thinking choice, remembered per person (COST-FAST-1). Kept in this browser only:
// `localStorage` keyed by the signed-in email (the same approach as the profile settings), with an in-memory
// fallback for when storage is absent or throws (private mode, blocked site data). Thinking is the default: it is
// what every start has been, so nothing changes for a person who never chooses.
import type { Effort } from "../../api/types";

export const DEFAULT_EFFORT: Effort = "thinking";

const PREFIX = "tilo.park.effort.";
/** The signed-in email is not known until the user read lands; until then the choice is the device's. */
const ANON = "anonymous";

/** In-memory fallback, per key, for the life of the page: only what storage refused to keep (or could not be read). */
const memory = new Map<string, Effort>();

const keyOf = (email: string | null | undefined): string =>
  `${PREFIX}${email ? email.trim().toLowerCase() : ANON}`;

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
