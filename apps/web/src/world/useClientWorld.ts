// FR-WLD-05 / Bundle B2 of #227: the one path that draws /world/:id from the client. The stage
// shows the run the active TiloClient serves (its layout and its events, the same ones the HUD and
// the lenses read), whether that client is the fixture client or the HTTP one. Like useWorldFixture
// it hands Stage a seam, so nothing is fetched or drawn before the Pixi container exists; with no
// world address it is inactive and the stage keeps its bare grid. The layout is read through
// `client.getLayout`, which waits, honestly, until the run has built one (world.started). Nothing
// is drawn before it exists and nothing moves without an event (HR-1, HR-2); events held on
// arrival fold in as a jump, later ones animate (runClientWorld).
import type { Layout } from "@tilo/contracts";
import type { Container } from "pixi.js";
import { useCallback, useEffect, useRef, useState } from "react";
import type { TiloClient } from "../api/client";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { describeError } from "../screens/remote";
import type { WorldSeam } from "../stage/Stage";
import { watchRun } from "./runLog";
import { runClientWorld } from "./runWorld";
import { useSelection } from "./selection";

const NO_MAP =
  "This world's map has not been laid out yet, so the stage stays empty. The team and every event show beside it and in the Story.";

export interface ClientWorldState {
  /** True when a world is addressed: the stage takes this hook's seam, selection and seq. */
  readonly active: boolean;
  /** The highest event seq drawn (the stage's `data-seq`). */
  readonly seq: number;
  /** The world's selected object (FR-WLD-06), for the stage frame's data-selected. */
  readonly selected: string | null;
  readonly onWorld: WorldSeam;
  /** The loaded layout and the world it belongs to, for the keyboard outline (FR-WLD-11). */
  readonly layout: Layout | null;
  readonly worldId: string;
  /** What a person reads while the world is not on the stage, or null once it is. */
  readonly note: string | null;
  /** Set when the world could not be loaded: asks again. */
  readonly retry: (() => void) | null;
}

interface Host {
  readonly world: Container;
  readonly requestRender: () => void;
  readonly size: () => { width: number; height: number };
}

/** `worldId` is the world to draw, or null (no world in the address, or a ?fixture= replay). */
export function useClientWorld(client: TiloClient, worldId: string | null): ClientWorldState {
  const [host, setHost] = useState<Host | null>(null);
  const [seq, setSeq] = useState(0);
  const [note, setNote] = useState<string | null>(null);
  const [layout, setLayout] = useState<Layout | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [selected] = useSelection(worldId ?? "");
  const reducedMotion = useRef(false);
  reducedMotion.current = useMediaQuery("(prefers-reduced-motion: reduce)");

  // The stage hands its Pixi container over once, when its renderer is ready.
  const onWorld = useCallback<WorldSeam>((world, requestRender, size) => {
    setHost({ world, requestRender, size });
    return () => setHost(null);
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` is the retry trigger.
  useEffect(() => {
    if (worldId === null || host === null) return;
    const { world, requestRender, size } = host;
    const before = world.children.length;
    let cancelled = false;
    let stop: (() => void) | undefined;
    setSeq(0);
    setLayout(null);
    setFailed(false);
    setNote("Waiting for the run to build its world…");
    client.getLayout(worldId).then(
      (layout) => {
        if (cancelled) return;
        setLayout(layout);
        // Geometry comes from the solver only (WE-09); a layout the server sent without it has
        // nothing to place, and nothing is invented here: the stage stays empty and says so.
        setNote(layout.geometry ? null : NO_MAP);
        stop = runClientWorld({
          world,
          requestRender,
          size,
          layout,
          watch: (onEvent) => watchRun(client, worldId, onEvent),
          reducedMotion: () => reducedMotion.current,
          onSeq: (n) => !cancelled && setSeq(n), // no onTrace: the Trace lens lists every event
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
    active: worldId !== null,
    seq,
    selected: worldId === null ? null : selected,
    onWorld,
    layout: worldId === null ? null : layout,
    worldId: worldId ?? "",
    note: worldId === null ? null : note,
    retry: failed ? retry : null,
  };
}
