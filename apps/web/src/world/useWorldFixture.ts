// P1/P6/P8: reads the `fixture`/`seq`/`speed` URL params (apps/web/CLAUDE.md), loads the named
// fixture (fixtureLoader.ts) and plays it into the Pixi world container Stage.tsx hands over
// (runWorld.ts), exposing just enough state for App.tsx to render the Trace list, the speed
// badge and the permanent "Fixture replay" label (HR-4/BQ-07).
import { useCallback, useMemo, useRef, useState } from "react";
import { useMediaQuery } from "../hooks/useMediaQuery";
import type { WorldSeam } from "../stage/Stage";
import { loadFixture } from "./fixtureLoader";
import type { RunStatus } from "./runSummary";
import { runWorld } from "./runWorld";
import { useSelection } from "./selection";
import { parseSpeed, speedBadgeText } from "./speed";

export interface WorldFixtureState {
  readonly active: boolean;
  readonly seq: number;
  readonly trace: ReadonlyArray<{ seq: number; type: string }>;
  readonly speedLabel: string | null;
  /** The replayed run's recorded status (FR-WLD-07: "paused" shows the veil). */
  readonly status: RunStatus;
  /** The run's selected object (FR-WLD-06), for the stage frame's data-selected. */
  readonly selected: string | null;
  /** Set when the named fixture could not be loaded (or no name was given); shown as an alert. */
  readonly loadError: string | null;
  readonly onWorld: WorldSeam;
}

function parseParams(search: string) {
  const params = new URLSearchParams(search);
  const fixture = params.get("fixture");
  const seqRaw = params.get("seq");
  const seqParam = seqRaw !== null && Number.isFinite(Number(seqRaw)) ? Number(seqRaw) : null;
  const speed = parseSpeed(params.get("speed"));
  return { fixture, seqParam, speed };
}

export function useWorldFixture(): WorldFixtureState {
  const { fixture, seqParam, speed } = useMemo(() => parseParams(window.location.search), []);
  const reducedMotionRef = useRef(false);
  reducedMotionRef.current = useMediaQuery("(prefers-reduced-motion: reduce)");
  const [seq, setSeq] = useState(0);
  const [status, setStatus] = useState<RunStatus>("idle");
  const [loadError, setLoadError] = useState<string | null>(
    fixture === "" ? "No fixture name was given, so the fixture could not be loaded." : null,
  );
  const [worldId, setWorldId] = useState(""); // set once the layout is loaded
  const [selected] = useSelection(worldId);
  const [trace, setTrace] = useState<ReadonlyArray<{ seq: number; type: string }>>([]);
  const stopRef = useRef<(() => void) | undefined>(undefined);
  // P7/HR-2 ("nothing moves before the first event"): the fetch starts only once Stage's Pixi
  // world container is ready and this seam fires (Stage.tsx calls it from inside its own
  // `app.init().then(...)`, after the page itself has loaded) — never eagerly during React's
  // render. Starting it at render time races ahead of the page's own load, so by the time a
  // caller can observe "still loading" (a slow connection, or a test's page.route delay) most of
  // that window has already elapsed and the fixture is done loading. Idempotent across React
  // StrictMode's dev-only double effect invocation, which can call this seam twice.
  const dataRef = useRef<Promise<import("./fixtureLoader").LoadedFixture> | null>(null);

  const onWorld = useCallback<WorldSeam>(
    (world, requestRender) => {
      if (!fixture) return undefined;
      if (!dataRef.current) dataRef.current = loadFixture(fixture);
      let cancelled = false;
      dataRef.current
        .then(({ layout, events }) => {
          if (cancelled) return;
          setWorldId(layout.world_id);
          stopRef.current = runWorld({
            world,
            requestRender,
            layout,
            events,
            seqParam,
            speed,
            reducedMotion: () => reducedMotionRef.current,
            onSeq: (n) => !cancelled && setSeq(n),
            onTrace: (t) => !cancelled && setTrace(t),
            onStatus: (s) => !cancelled && setStatus(s),
          });
        })
        .catch(() => {
          // A missing, non-JSON or malformed fixture: surfaced in-app, never on the console.
          if (!cancelled) setLoadError(`Fixture "${fixture}" could not be loaded.`);
        });
      return () => {
        cancelled = true;
        stopRef.current?.();
        stopRef.current = undefined;
      };
    },
    [fixture, seqParam, speed],
  );

  return {
    active: fixture !== null,
    seq,
    trace,
    speedLabel: speedBadgeText(speed),
    status,
    selected,
    loadError,
    onWorld,
  };
}
