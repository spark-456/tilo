// S-05 Inspect panel (PRD 18.3): one thing in the world (agent, building, district, level, island
// or artifact), what it is, where it sits, its state and every recorded event that names it. State
// comes from the reducer over the recorded events, never from a guess (HR-1, HR-5). Layout after
// the Inspect panel in design/source "Tilo World Player.dc.html".
import { useEffect } from "react";
import { useClient } from "../api/ClientProvider";
import { reduce } from "../world/reducer";
import { elapsed, useRunLog } from "../world/runLog";
import { involves, select } from "../world/selection";
import { AppLink } from "./AppLink";
import { Loaded } from "./FlowShell";
import { Placeholder } from "./Placeholder";
import { SelectionBar } from "./SelectionBar";
import { findItem } from "./findItem";
import { useRemote } from "./remote";
import type { ScreenProps } from "./routes";

export { findItem };

export function S_05({ params }: ScreenProps) {
  const [worldId = "", itemId = ""] = params;
  const client = useClient();
  const events = useRunLog(client, worldId);
  const [layout, retry] = useRemote("load the world", () => client.getLayout(worldId));
  const found = layout.status === "ready" ? findItem(layout.value, itemId, events) : null;
  const exists = found !== null;
  // Inspecting an object selects it, so the lenses show the same one (FR-WLD-06).
  useEffect(() => {
    if (exists) select(worldId, itemId);
  }, [exists, worldId, itemId]);
  return (
    <div className="screen-body wide" data-testid="inspect-panel">
      <p>
        <AppLink className="back-link" to={`/world/${encodeURIComponent(worldId)}`}>
          Back to the world
        </AppLink>
      </p>
      <h1>{layout.status === "ready" ? (found ? found.name : "Not found") : "Inspect"}</h1>
      <SelectionBar worldId={worldId} />
      <Loaded what="the world" remote={layout} retry={retry} isEmpty={() => false}>
        {(l) => {
          const item = findItem(l, itemId, events);
          if (!item) return <p>There is nothing called {itemId} in this world.</p>;
          const mine = events.filter((e) => involves(e, itemId));
          return (
            <>
              <p className="screen-tag">
                {item.kind} · {item.where}
              </p>
              <p>
                <b>State:</b> {item.state(reduce(l, events))}
              </p>
              <Placeholder label="Follow in the world" />
              <h2>What happened here</h2>
              {mine.length === 0 ? (
                <p>No event has named this yet.</p>
              ) : (
                <ol className="story-list">
                  {mine.map((e) => (
                    <li key={e.seq}>
                      <span className="story-time">{elapsed(events, e)}</span>
                      <span>{e.summary}</span>
                    </li>
                  ))}
                </ol>
              )}
            </>
          );
        }}
      </Loaded>
    </div>
  );
}
