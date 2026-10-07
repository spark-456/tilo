// When the city is drawn (NFR-01, ticket NFR-01-LANDING). The city is about ten full-size SVG pictures and
// twenty-odd cars and walkers, each its own SVG: building it and letting the browser decode and paint it
// takes seconds on a phone, so the shell paints the page first (composer, panels, nav) and starts the city only
// once the shell is ready and a short grace has passed. Until then the backdrop shows a poster in the same
// fixed box (CityBackdrop), so the city arriving moves nothing. The wait goes through the provider's injected
// scheduler, the shell's only timer (a test fires it by hand). Once started, a change of theme or motion draws
// the new scene at once: that is the person's own click, and the cache makes the way back free.
import { useEffect, useMemo, useState } from "react";
import { useSchedule } from "../app/context";
import type { CityMotion } from "./cityMotion";
import { type BackdropScene, backdropScene } from "./scene";

/** How long after the shell is ready the city is requested. */
export const CITY_DEFER_MS = 1200;

/** The city for `time|motion`, or null until it is due (the poster stands in). */
export function useCityScene(
  time: "day" | "night",
  motion: CityMotion,
  ready: boolean,
): BackdropScene | null {
  const schedule = useSchedule();
  const [started, setStarted] = useState(false);
  useEffect(() => {
    if (!ready || started) return undefined;
    return schedule(() => setStarted(true), CITY_DEFER_MS);
  }, [ready, started, schedule]);
  return useMemo(() => (started ? backdropScene(time, motion) : null), [started, time, motion]);
}
