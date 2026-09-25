import { useEffect, useState } from "react";

/** Reactive `window.matchMedia` (used for the mobile breakpoint and
 * `prefers-reduced-motion`) so layout and motion are real display settings,
 * not a separate build/code path (PRD 9.6 "Stage mode ... display settings"). */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(
    () => typeof window !== "undefined" && window.matchMedia(query).matches,
  );

  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}
