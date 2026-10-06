// The world this session started last: the id `approve` returned (S-03). A bare Needs-you or Library
// address names no world, so with a live API it falls back to this one, and to "No run yet" when
// there is none (CP2, #258). Held in memory for the page's lifetime: nothing is stored or guessed.
import { useSyncExternalStore } from "react";

let last: string | null = null;
const listeners = new Set<() => void>();

function set(worldId: string | null): void {
  if (last === worldId) return;
  last = worldId;
  for (const listener of [...listeners]) listener();
}

/** Remember the world a run just started in. */
export const rememberWorld = (worldId: string): void => set(worldId);

/** Forget it (tests only). */
export const forgetWorld = (): void => set(null);

const subscribe = (onChange: () => void) => {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
};

/** The world this session started last, or null when it has started none. */
export const useLastStartedWorld = (): string | null => useSyncExternalStore(subscribe, () => last);
