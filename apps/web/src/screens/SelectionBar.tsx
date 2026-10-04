// FR-WLD-06: says which object the lenses are following, in words (colour never carries it alone),
// and opens its Inspect screen or clears it. It is on every lens screen and keeps one fixed height,
// so choosing or clearing moves nothing (CLS).
import { useClient } from "../api/ClientProvider";
import { useRunLog } from "../world/runLog";
import { useSelection } from "../world/selection";
import { AppLink } from "./AppLink";
import { findItem } from "./findItem";
import { useRemote } from "./remote";

export function SelectionBar({ worldId }: { worldId: string }) {
  const client = useClient();
  const events = useRunLog(client, worldId);
  const [layout] = useRemote("load the world", (signal) => client.getLayout(worldId, signal));
  const [id, set] = useSelection(worldId);
  const item = id && layout.status === "ready" ? findItem(layout.value, id, events) : null;
  return (
    <div className="selection-bar" data-testid="selection-bar" data-selected-id={id ?? ""}>
      <span className="selection-text">
        {id ? (
          <>
            Selected: <b>{item?.name ?? id}</b>
            {item && <small> {item.kind}</small>}
          </>
        ) : (
          "Nothing selected"
        )}
      </span>
      {id && (
        <>
          <AppLink to={`/world/${encodeURIComponent(worldId)}/inspect/${encodeURIComponent(id)}`}>
            Inspect
          </AppLink>
          <button type="button" className="pick" data-lens-control onClick={() => set(null)}>
            Clear
          </button>
        </>
      )}
    </div>
  );
}
