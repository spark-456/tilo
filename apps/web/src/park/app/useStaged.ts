// A heavy page draws itself in parts (WEB-MOTION-2: no long task while pages change). In a browser the first
// part is drawn at once and each next part one task later (the provider's injected scheduler, with the work in a
// transition so React slices it), so no single commit holds the main thread for long; parts are drawn top to
// bottom and only ever added below or after what is already there, so nothing on screen moves. Where there is no
// CSS animation engine (the DOM stand-ins in unit tests) every part is drawn at the first render, as before.
import { startTransition, useEffect, useState } from "react";
import { useSchedule } from "./context";

/** How many of `parts` are drawn now (1 to `parts`). */
export function useStagedCount(parts: number): number {
  const schedule = useSchedule();
  const staged = typeof CSSAnimation !== "undefined";
  const [drawn, setDrawn] = useState(1);
  const now = staged ? Math.min(drawn, Math.max(1, parts)) : parts; // `parts` may grow once data arrives
  useEffect(() => {
    if (!staged || now >= parts) return undefined;
    return schedule(() => startTransition(() => setDrawn(now + 1)), 0);
  }, [staged, now, parts, schedule]);
  return now;
}

/** `part(n)` is true when part n (1-based) is drawn. */
export function useStaged(parts: number): (n: number) => boolean {
  const count = useStagedCount(parts);
  return (n) => n <= count;
}

/** False for the first render and true one task later (always true where there is no CSS animation engine): for
 * the heaviest part of a component whose box does not depend on it, so its text is drawn a task earlier. */
export function useAfterTask(): boolean {
  const schedule = useSchedule();
  const staged = typeof CSSAnimation !== "undefined";
  const [late, setLate] = useState(false);
  useEffect(() => {
    if (!staged) return undefined;
    return schedule(() => startTransition(() => setLate(true)), 0);
  }, [staged, schedule]);
  return !staged || late;
}
