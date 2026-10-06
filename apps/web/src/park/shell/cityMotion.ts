// How the shell chooses the city's motion (README "Interactions and motion", "City backdrop", "Performance").
// The person's preference (lively, calm, still) is overridden, never raised: reduced motion or the ambient
// switch off means a frozen city; a weak device (4 cores or fewer, or 4 GB or less) means calm. The result is
// part of the scene's cache key, so each choice is drawn once. `lite` is the sprite cap (a narrow window or a
// weak device): half the movers are not drawn. `hidden` is a tab nobody is looking at.
import { useMemo, useSyncExternalStore } from "react";
import { AMBIENT_ON } from "./ambient";

export type CityMotion = "lively" | "calm" | "still";

const REDUCE = "(prefers-reduced-motion: reduce)";
/** The window width under which the sprite cap applies (README breakpoint). */
export const NARROW_PX = 768;

function subscribeReduced(on: () => void): () => void {
  if (typeof window.matchMedia !== "function") return () => undefined;
  const list = window.matchMedia(REDUCE);
  list.addEventListener("change", on);
  return () => list.removeEventListener("change", on);
}
const reducedNow = (): boolean =>
  typeof window.matchMedia === "function" && window.matchMedia(REDUCE).matches;

function subscribeVisible(on: () => void): () => void {
  document.addEventListener("visibilitychange", on);
  return () => document.removeEventListener("visibilitychange", on);
}
const hiddenNow = (): boolean => document.hidden;

/** 4 cores or fewer, or 4 GB or less; a browser that does not say is taken as strong. */
export function weakDevice(): boolean {
  const n = navigator as Navigator & { deviceMemory?: number };
  const cores = n.hardwareConcurrency;
  const memory = n.deviceMemory;
  return (
    (typeof cores === "number" && cores > 0 && cores <= 4) ||
    (typeof memory === "number" && memory > 0 && memory <= 4)
  );
}

export function useCityMotion(
  pref: string,
  vw: number,
): { motion: CityMotion; lite: boolean; hidden: boolean } {
  const reduced = useSyncExternalStore(subscribeReduced, reducedNow);
  const hidden = useSyncExternalStore(subscribeVisible, hiddenNow);
  const weak = useMemo(weakDevice, []);
  const motion: CityMotion =
    !AMBIENT_ON || reduced || pref === "still"
      ? "still"
      : weak || pref === "calm"
        ? "calm"
        : "lively";
  return { motion, lite: motion !== "still" && (weak || vw < NARROW_PX), hidden };
}
