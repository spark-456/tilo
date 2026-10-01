import { useSyncExternalStore } from "react";

/** Live `matchMedia` result, so breakpoints and reduced motion are display settings (PRD 9.6). */
export const useMediaQuery = (query: string) =>
  useSyncExternalStore(
    (onChange) => {
      const mql = window.matchMedia(query);
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
  );
