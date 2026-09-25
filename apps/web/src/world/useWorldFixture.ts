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
  // Fetches as soon as the fixture name is known, not gated behind the Pixi world container
  // becoming ready (WorldSeam fires once WebGL init resolves), so the network round trip and
  // the renderer's own init overlap instead of running one after the other (HR-2's "nothing
  // moves before the first event" still holds: runWorld only starts once this resolves AND the
  // seam has fired). Idempotent across React StrictMode's dev-only double render.
  const dataRef = useRef<Promise<import("./fixtureLoader").LoadedFixture> | null>(null);
  if (fixture && !dataRef.current) dataRef.current = loadFixture(fixture);

  const onWorld = useCallback<WorldSeam>(
    (world, requestRender) => {
      if (!fixture || !dataRef.current) return undefined;
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
