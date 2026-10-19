// ADR-0035 LC-02: the first thing the callback route does. The address carries Google's one-time `code` and the `state`;
// both leave the address bar and the history entry (`history.replaceState`) before anything else runs (sign-in, a
// render, a request). They are held in memory only, once: a second render or a React double-run gets the same value, and
// nothing is written to storage, a log or the document.
import type { CallbackParams } from "../api/connect";

const MAX = 600;
let taken: { params: CallbackParams | null } | null = null;

const word = (v: string | null): string | undefined =>
  v !== null && v.length > 0 && v.length <= MAX ? v : undefined;

/** Strips the query and fragment from the address, then returns what they held (null when there was no `state`). */
export function takeCallbackParams(win: Window = window): CallbackParams | null {
  if (taken) return taken.params;
  const query = new URLSearchParams(win.location.search);
  const { pathname } = win.location;
  try {
    win.history.replaceState(null, "", pathname);
  } catch {
    // an address that cannot be replaced is left; the values are still held below and never shown
  }
  const state = word(query.get("state"));
  const code = word(query.get("code"));
  const error = word(query.get("error"));
  const params: CallbackParams | null = state
    ? { state, ...(code ? { code } : {}), ...(error ? { error } : {}) }
    : null;
  taken = { params };
  return params;
}

/** Test support: forget what was taken. */
export function forgetCallbackParams(): void {
  taken = null;
}
