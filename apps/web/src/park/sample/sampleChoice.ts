// STARTER-1: the sample project, and what a person chose to do with it. The server stores nothing about it: a
// "Hide" is this browser's (localStorage, with an in-memory fallback when storage is absent or throws), and
// "Show sample project" asks `GET /worlds?include_sample=1` once the person has worlds of their own.
export const SAMPLE_WORLD_ID = "w_sample_village_basic";
export const SAMPLE_NOTE = "A recorded sample replay, not your work.";

const HIDDEN_KEY = "tilo.park.sample.hidden";
const SHOWN_KEY = "tilo.park.sample.shown";

const memory = new Map<string, boolean>();

function read(key: string): boolean {
  try {
    const stored = window.localStorage.getItem(key);
    if (stored === "1") return true;
    if (stored === "0") return false;
  } catch {
    // storage absent or blocked: the in-memory value below
  }
  return memory.get(key) ?? false;
}

function write(key: string, value: boolean): void {
  try {
    window.localStorage.setItem(key, value ? "1" : "0");
    memory.delete(key);
  } catch {
    memory.set(key, value); // storage would not keep it: remembered for this page only
  }
}

/** The person hid the sample project in this browser. */
export const isSampleHidden = (): boolean => read(HIDDEN_KEY);

/** The person asked for the sample project although they have worlds of their own. */
export const wantsSample = (): boolean => read(SHOWN_KEY) && !read(HIDDEN_KEY);

export function hideSample(): void {
  write(HIDDEN_KEY, true);
  write(SHOWN_KEY, false);
}

export function showSample(): void {
  write(HIDDEN_KEY, false);
  write(SHOWN_KEY, true);
}
