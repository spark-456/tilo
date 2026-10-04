// The display density mode (PRD 18.3 S-22, 18.2, FR-WLD-14): Friendly (the default) or Professional.
// It is a display setting, never an event: it changes how the app is drawn and nothing the run
// recorded. The choice is kept in this browser (localStorage, when it is allowed) and written to
// `data-density` on <html> as soon as it changes, so the page and the stage can read it live.
import { useSyncExternalStore } from "react";

export type Density = "friendly" | "professional";
const KEY = "tilo.density";
const listeners = new Set<() => void>();

function read(): Density {
  try {
    return window.localStorage.getItem(KEY) === "professional" ? "professional" : "friendly";
  } catch {
    return "friendly"; // storage blocked or absent: the default look
  }
}

let current: Density = read();

const apply = (d: Density): void => {
  document.documentElement.dataset.density = d;
};

/** Applies the saved mode to the page. Call once before the first render. */
export function initDensity(): void {
  current = read();
  apply(current);
}

export const getDensity = (): Density => current;

export function setDensity(next: Density): void {
  if (next === current) return;
  current = next;
  apply(next);
  try {
    window.localStorage.setItem(KEY, next);
  } catch {
    // The mode still applies for this visit; it is just not remembered.
  }
  for (const l of [...listeners]) l();
}

const subscribe = (onChange: () => void): (() => void) => {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
};

export const useDensity = (): readonly [Density, (d: Density) => void] => [
  useSyncExternalStore(subscribe, getDensity),
  setDensity,
];
