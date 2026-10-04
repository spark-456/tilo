// FR-WLD-05: the stage draws a live run. When the client is not the fixture client, the world a
// /world/:id address names is read through `client.getLayout` (it waits, honestly, until the run
// has built one) and `followRun` (the page's one event subscription) feeds every recorded event
// through the same reducer, choreographer and renderer as a fixture replay (runWorld.ts, `live`).
// Nothing is drawn before the layout exists and nothing moves without an event (HR-1, HR-2).
import type { Container } from "pixi.js";
import { useCallback, useEffect, useRef, useState } from "react";
import type { TiloClient } from "../api/client";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { describeError } from "../screens/remote";
import type { WorldSeam } from "../stage/Stage";
import { followRun } from "./runLog";
import { runWorld } from "./runWorld";
import { useSelection } from "./selection";

const NO_MAP =
  "This world's map has not been laid out yet, so the stage stays empty. The team and every event show beside it and in the Story.";

export interface LiveWorldState {
  readonly onWorld: WorldSeam;
  /** The highest event seq drawn (the stage's `data-seq`). */
  readonly seq: number;
  /** What a person reads while the world is not on the stage, or null once it is. */
  readonly note: string | null;
  /** The world's selected object (FR-WLD-06), for the stage frame's data-selected. */
  readonly selected: string | null;
  /** Set when the world could not be loaded: asks again. */
  readonly retry: (() => void) | null;
}

interface Host {
  readonly world: Container;
  readonly requestRender: () => void;
}

/** `worldId` is the live world to draw, or null (a fixture client, or no world in the address). */
export function useLiveWorld(client: TiloClient, worldId: string | null): LiveWorldState {
  const [host, setHost] = useState<Host | null>(null);
  const [seq, setSeq] = useState(0);
  const [note, setNote] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [selected] = useSelection(worldId ?? "");
  const reducedMotion = useRef(false);
  reducedMotion.current = useMediaQuery("(prefers-reduced-motion: reduce)");

  // The stage hands its Pixi container over once, when its renderer is ready.
  const onWorld = useCallback<WorldSeam>((world, requestRender) => {
    setHost({ world, requestRender });
    return () => setHost(null);
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` is the retry trigger.
  useEffect(() => {
    if (worldId === null || host === null) return;
    const { world, requestRender } = host;
    const before = world.children.length;
    let cancelled = false;
    let stop: (() => void) | undefined;
    setSeq(0);
    setFailed(false);
    setNote("Waiting for the run to build its world…");
    client.getLayout(worldId).then(
      (layout) => {
        if (cancelled) return;
        // Geometry comes from the solver only (WE-09); a layout the server sent without it has
        // nothing to place, and nothing is invented here: the stage stays empty and says so.
        setNote(layout.geometry ? null : NO_MAP);
        stop = runWorld({
          world,
          requestRender,
          layout,
          events: [],
          seqParam: null,
          speed: 1,
          reducedMotion: () => reducedMotion.current,
          onSeq: (n) => !cancelled && setSeq(n),
          onTrace: () => undefined, // the Trace lens lists every event
          live: (apply) => followRun(client, worldId, apply),
        });
      },
      (error: unknown) => {
        if (cancelled) return;
        setFailed(true);
        setNote(describeError("load the world", error));
      },
    );
    return () => {
      cancelled = true;
      stop?.();
      if (!world.destroyed) {
        for (const child of world.removeChildren(before)) child.destroy();
        requestRender();
      }
    };
  }, [client, worldId, host, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return {
    onWorld,
    seq,
    selected,
    note: worldId === null ? null : note,
    retry: failed ? retry : null,
  };
}
