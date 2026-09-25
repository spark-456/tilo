// P1/P6/P8: reads the `fixture`/`seq`/`speed` URL params (apps/web/CLAUDE.md), loads the named
// fixture (fixtureLoader.ts) and plays it into the Pixi world container Stage.tsx hands over
// (runWorld.ts), exposing just enough state for App.tsx to render the Trace list, the speed
// badge and the permanent "Fixture replay" label (HR-4/BQ-07).
import { useCallback, useMemo, useRef, useState } from "react";
import { useMediaQuery } from "../hooks/useMediaQuery";
import type { WorldSeam } from "../stage/Stage";
import { loadFixture } from "./fixtureLoader";
import { runWorld } from "./runWorld";

export interface WorldFixtureState {
  readonly active: boolean;
  readonly seq: number;
  readonly trace: ReadonlyArray<{ seq: number; type: string }>;
  readonly speedLabel: string | null;
  readonly onWorld: WorldSeam;
}

function parseParams(search: string) {
  const params = new URLSearchParams(search);
  const fixture = params.get("fixture");
  const seqRaw = params.get("seq");
  const seqParam = seqRaw !== null && Number.isFinite(Number(seqRaw)) ? Number(seqRaw) : null;
  const speedRaw = Number(params.get("speed"));
  const speed = Number.isFinite(speedRaw) && speedRaw > 0 ? speedRaw : 1;
  return { fixture, seqParam, speed };
}

export function useWorldFixture(): WorldFixtureState {
  const { fixture, seqParam, speed } = useMemo(() => parseParams(window.location.search), []);
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const [seq, setSeq] = useState(0);
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
          stopRef.current = runWorld({
            world,
            requestRender,
            layout,
            events,
            seqParam,
            speed,
            reducedMotion,
            onSeq: (n) => !cancelled && setSeq(n),
            onTrace: (t) => !cancelled && setTrace(t),
          });
        })
        .catch((err: unknown) => {
          if (!cancelled) console.error("fixture mode: failed to load", fixture, err);
        });
      return () => {
        cancelled = true;
        stopRef.current?.();
        stopRef.current = undefined;
      };
    },
    [fixture, seqParam, speed, reducedMotion],
  );

  return {
    active: fixture !== null,
    seq,
    trace,
    speedLabel: speed > 1 ? `${speed}×` : null,
    onWorld,
  };
}
