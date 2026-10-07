// When and how the city is drawn (NFR-01, ticket NFR-01-LANDING). The city is about ten full-size SVG pictures
// and twenty-odd cars and walkers, each its own SVG: building it and letting the browser decode and paint it takes
// seconds on a phone. So the shell paints the page first (composer, panels, nav) and starts the city only once the
// shell is ready and a short grace has passed; until then the backdrop shows a poster in the same fixed box
// (CityBackdrop), so the city arriving moves nothing. The city is then built in slices (park.ts `sceneSteps`: a
// few milliseconds of work, then a pause) so the page stays typeable while it is drawn, and it is shown only
// when it is whole. Every wait goes through the provider's injected scheduler, the shell's only timer (a test
// fires it by hand). Once the first city is up, a change of theme or motion draws the new scene at once: that is
// the person's own click, and the cache makes the way back free.
import { useEffect, useMemo, useState } from "react";
import { useSchedule } from "../app/context";
import type { CityMotion } from "./cityMotion";
import { type BackdropScene, backdropScene, backdropSceneSteps, isDrawn } from "./scene";

/** How long after the shell is ready the city is requested. */
export const CITY_DEFER_MS = 1200;
/** The pause between two slices of the build, so input and paint get their turn. */
export const CITY_SLICE_MS = 8;
/** How long one slice may run before it pauses. */
const SLICE_BUDGET_MS = 16;

/** The city for `time|motion`, or null until it is drawn (the poster stands in). */
export function useCityScene(
  time: "day" | "night",
  motion: CityMotion,
  ready: boolean,
): BackdropScene | null {
  const schedule = useSchedule();
  const [started, setStarted] = useState(false);
  const [live, setLive] = useState(false);
  useEffect(() => {
    if (!ready || started) return undefined;
    return schedule(() => setStarted(true), CITY_DEFER_MS);
  }, [ready, started, schedule]);
  useEffect(() => {
    if (!started || live) return undefined;
    if (isDrawn(time, motion)) {
      setLive(true);
      return undefined;
    }
    const steps = backdropSceneSteps(time, motion);
    let cancel: (() => void) | undefined;
    const slice = (): void => {
      const from = performance.now();
      for (;;) {
        if (steps.next().done) {
          setLive(true);
          return;
        }
        if (performance.now() - from >= SLICE_BUDGET_MS) break;
      }
      cancel = schedule(slice, CITY_SLICE_MS);
    };
    slice();
    return () => {
      cancel?.();
      steps.return();
    };
  }, [started, live, time, motion, schedule]);
  return useMemo(() => (live ? backdropScene(time, motion) : null), [live, time, motion]);
}
