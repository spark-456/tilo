// STUDIO-6: the two browser preferences the signed-out pages follow, read live. Dependency-free (the sign-in screen is
// in the entry chunk). A browser without matchMedia, or one that throws, reads as light and full motion.
import { useState, useSyncExternalStore } from "react";

function query(q: string): MediaQueryList | null {
  try {
    return typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(q)
      : null;
  } catch {
    return null;
  }
}

function useMedia(q: string): boolean {
  return useSyncExternalStore(
    (change) => {
      const list = query(q);
      if (!list || typeof list.addEventListener !== "function") return () => undefined;
      list.addEventListener("change", change);
      return () => list.removeEventListener("change", change);
    },
    () => query(q)?.matches === true,
    () => false,
  );
}

/** True when the browser asks for a dark page. */
export const usePrefersDark = (): boolean => useMedia("(prefers-color-scheme: dark)");

/** Light or dark: the browser's choice until the person flips it on this page (not remembered). */
export function useNightToggle(): readonly [boolean, () => void] {
  const system = usePrefersDark();
  const [chosen, setChosen] = useState<boolean | null>(null);
  const night = chosen ?? system;
  return [night, () => setChosen(!night)];
}

/** True when the browser asks for reduced motion. */
export const usePrefersReducedMotion = (): boolean => useMedia("(prefers-reduced-motion: reduce)");
