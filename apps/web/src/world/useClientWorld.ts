// Bundle B2 of #227: the stage on /world/:id draws the run the active TiloClient serves (its layout
// and its events, the same ones the HUD and the lenses read), not only a ?fixture= replay. Like
// useWorldFixture it hands Stage a seam, so nothing is fetched or drawn before the Pixi container
// exists; with no world address it is inactive and the stage keeps its bare grid.
import { useCallback, useRef, useState } from "react";
import { useClient } from "../api/ClientProvider";
import { useMediaQuery } from "../hooks/useMediaQuery";
import type { WorldSeam } from "../stage/Stage";
import { watchRun } from "./runLog";
import { runClientWorld } from "./runWorld";
import { useSelection } from "./selection";

export interface ClientWorldState {
  readonly active: boolean;
  readonly seq: number;
  readonly selected: string | null;
  readonly onWorld: WorldSeam;
}

/** `?seq=N` shows the run as it stood at seq N, the same jump the fixture replay offers (HR-6). */
function seqParam(): number | null {
  const raw = new URLSearchParams(window.location.search).get("seq");
  return raw !== null && Number.isFinite(Number(raw)) ? Number(raw) : null;
}

export function useClientWorld(worldId: string | null): ClientWorldState {
  const client = useClient();
  const reducedMotion = useRef(false);
  reducedMotion.current = useMediaQuery("(prefers-reduced-motion: reduce)");
  const [seq, setSeq] = useState(0);
  const [selected] = useSelection(worldId ?? "");

  const onWorld = useCallback<WorldSeam>(
    (world, requestRender, size) => {
      if (worldId === null) return undefined;
      let cancelled = false;
      let stop: (() => void) | undefined;
      setSeq(0);
      client
        .getLayout(worldId)
        .then((layout) => {
          if (cancelled) return;
          stop = runClientWorld({
            world,
            requestRender,
            size,
            layout,
            seqParam: seqParam(),
            watch: (onEvent) => watchRun(client, worldId, onEvent),
            reducedMotion: () => reducedMotion.current,
            onSeq: (n) => !cancelled && setSeq(n),
            onTrace: () => undefined, // the Trace lens reads the run log itself
          });
        })
        // A layout that cannot load is shown by the HUD (WorldPanels), which asks for the same one.
        .catch(() => undefined);
      return () => {
        cancelled = true;
        stop?.();
      };
    },
    [client, worldId],
  );

  return { active: worldId !== null, seq, selected: worldId === null ? null : selected, onWorld };
}
