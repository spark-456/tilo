// The Inspect page (PRD 18.3): one thing in the world (agent, building, district, level, island or artifact), what
// it is, where it sits, its state and every recorded event that names it. State comes from the reducer over the
// recorded events, never from a guess (HR-1, HR-5).
import { type CSSProperties, useEffect } from "react";
import { useClient } from "../api/ClientProvider";
import { useRemote } from "../screens/remote";
import { findItem } from "../world/findItem";
import { reduce } from "../world/reducer";
import { useReplayedLog } from "../world/replay";
import { elapsed } from "../world/runLog";
import { involves, select } from "../world/selection";
import { LensFrame } from "./LensFrame";
import { LevelChip, levelOf } from "./LevelChip";
import { ViewLink } from "./ViewLink";
import { factsOf, stateTone } from "./inspectFacts";
import { lensPath } from "./routes";

export function InspectView({ worldId, itemId }: { worldId: string; itemId: string }) {
  const client = useClient();
  const { events } = useReplayedLog(client, worldId);
  const [layout, retry] = useRemote("load the world", (signal) =>
    client.getLayout(worldId, signal),
  );
  const found = layout.status === "ready" ? findItem(layout.value, itemId, events) : null;
  const exists = found !== null;
  // Inspecting an object selects it, so the lenses show the same one (FR-WLD-06).
  useEffect(() => {
    if (exists) select(worldId, itemId);
  }, [exists, worldId, itemId]);
  const title = layout.status === "ready" ? (found ? found.name : "Not found") : "Inspect";
  return (
    <LensFrame worldId={worldId} current="inspect" title={title}>
      <div data-testid="inspect-panel" className="park-view-body">
        {layout.status === "loading" ? (
          <p className="park-view-note">Loading the world…</p>
        ) : layout.status === "error" ? (
          <div className="park-view-alert" role="alert">
            <p>{layout.message}</p>
            <button type="button" className="park-view-chiplink" onClick={retry}>
              Try again
            </button>
          </div>
        ) : !found ? (
          <p className="park-view-note">There is nothing called {itemId} in this world.</p>
        ) : (
          <Found worldId={worldId} itemId={itemId} />
        )}
      </div>
    </LensFrame>
  );
}

function Found({ worldId, itemId }: { worldId: string; itemId: string }) {
  const client = useClient();
  const { events } = useReplayedLog(client, worldId);
  const [layout] = useRemote("load the world", (signal) => client.getLayout(worldId, signal));
  if (layout.status !== "ready") return null;
  const l = layout.value;
  const item = findItem(l, itemId, events);
  if (!item) return null;
  const mine = events.filter((e) => involves(e, itemId));
  const now = reduce(l, events);
  const state = item.state(now);
  const facts = factsOf(l, itemId, now);
  return (
    <>
      <p className="park-view-note">
        {item.kind} · {item.where}
      </p>
      <p className="park-view-state">
        <b>State:</b>{" "}
        <span className={`park-view-flag park-view-flag--${stateTone(state)}`}>{state}</span>
      </p>
      {facts.length > 0 ? (
        <dl
          className="park-view-facts"
          data-testid="inspect-facts"
          style={{ "--rows": facts.length } as CSSProperties}
        >
          {facts.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <p>
        <ViewLink className="park-view-chiplink" to={lensPath(worldId, "stage")}>
          Follow in the world
        </ViewLink>
      </p>
      <h2 className="park-view-h2">What happened here</h2>
      {mine.length === 0 ? (
        <p className="park-view-note">No event has named this yet.</p>
      ) : (
        <ol className="park-view-story" aria-label="Events that name this, in order">
          {mine.map((e) => {
            const lv = levelOf(l, e);
            return (
              <li key={e.seq}>
                <span className="park-view-time">{elapsed(events, e)}</span>
                <div className="park-view-storybody">
                  <p className="park-view-text">
                    {e.summary} {lv ? <LevelChip level={lv} /> : null}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </>
  );
}
