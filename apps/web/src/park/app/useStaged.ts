// A heavy page draws itself in parts (WEB-MOTION-2: no long task while pages change). In a browser the first
// part is drawn at once and each next part one task later (the provider's injected scheduler, with the work in a
// transition so React slices it), so no single commit holds the main thread for long; parts are drawn top to
// bottom and only ever added below what is already there, so nothing on screen moves. Where there is no CSS
// animation engine (the DOM stand-ins in unit tests) every part is drawn at the first render, as before.
import { startTransition, useEffect, useState } from "react";
import { useSchedule } from "./context";

/** How many of `parts` to draw now (1 to `parts`); `part(n)` is true when part n (1-based) is drawn. */
export function useStaged(parts: number): (n: number) => boolean {
  const schedule = useSchedule();
  const staged = typeof CSSAnimation !== "undefined";
  const [drawn, setDrawn] = useState(staged ? 1 : parts);
  useEffect(() => {
    if (drawn >= parts) return undefined;
    return schedule(() => startTransition(() => setDrawn(drawn + 1)), 0);
  }, [drawn, parts, schedule]);
  return (n) => n <= drawn;
}
