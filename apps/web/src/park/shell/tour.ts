// ONBOARD-1: the Park shell's seam to the first-run welcome and tour (src/onboarding/). Same idea as the sign-in seam
// (auth.tsx): the shell imports nothing from outside park/, and src/onboarding/register.ts (a chunk of its own, loaded by
// the Root) hands it the tour. `Layer` is drawn by ParkApp inside the `[data-park]` root; `start` is what the account
// menu's "Take the tour" calls. With no tour registered (tests, a chunk still loading) the menu has no such row and
// nothing is drawn.
import { type ComponentType, useSyncExternalStore } from "react";

export interface ParkTour {
  Layer: ComponentType;
  start: () => void;
}

let current: ParkTour | null = null;
const listeners = new Set<() => void>();

export function setParkTour(tour: ParkTour | null): void {
  current = tour;
  for (const l of [...listeners]) l();
}

const subscribe = (l: () => void): (() => void) => {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
};

/** The registered tour, or null. */
export const useParkTour = (): ParkTour | null =>
  useSyncExternalStore(
    subscribe,
    () => current,
    () => null,
  );
