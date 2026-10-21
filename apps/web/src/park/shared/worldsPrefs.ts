// WORLDS-MANAGE: how this browser orders the Worlds page and which worlds it pinned to the top. Per-viewer
// conveniences only: localStorage with try/catch (a blocked store keeps the choice for the visit), never sent anywhere,
// never read as anything the server said. Outside the page folder, which touches no window global (WEB_5_static).
const SORT_KEY = "tilo.worlds.sort";
const PIN_KEY = "tilo.worlds.pinned";

/** The stored sort key when it is one of `known`, else `fallback`. */
export function readSortPref<K extends string>(known: readonly K[], fallback: K): K {
  try {
    const v = window.localStorage.getItem(SORT_KEY);
    return known.find((k) => k === v) ?? fallback;
  } catch {
    return fallback;
  }
}

export function writeSortPref(sort: string): void {
  try {
    window.localStorage.setItem(SORT_KEY, sort);
  } catch {
    // storage blocked: the order still applies on this page
  }
}

export function readPinnedPref(): Set<string> {
  try {
    const v: unknown = JSON.parse(window.localStorage.getItem(PIN_KEY) ?? "[]");
    return new Set(Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

export function writePinnedPref(pinned: ReadonlySet<string>): void {
  try {
    window.localStorage.setItem(PIN_KEY, JSON.stringify([...pinned]));
  } catch {
    // storage blocked: the pins still apply on this page
  }
}
