// The Trace lens with archive links (PRD 18.3, 9.6): every recorded event as a two-line row, the type on top and
// below it actor to target, the model call, credits and the archive record, so the record is always in view (no
// sideways scroll). Unregistered types are listed too and marked: HR-5 puts them here and nowhere else.
import { useClient } from "../api/ClientProvider";
import { useRemote } from "../park/shared/remote";
import { isKnownType } from "../world/registry";
import { useReplayedLog } from "../world/replay";
import { elapsed } from "../world/runLog";
import { involves, objectIds, useSelection } from "../world/selection";
import { LensFrame } from "./LensFrame";

export function TraceView({ worldId }: { worldId: string }) {
  const client = useClient();
  const { events } = useReplayedLog(client, worldId);
  const [selected, , toggle] = useSelection(worldId);
  const [layout] = useRemote("load the world", (signal) => client.getLayout(worldId, signal));
  const ids = layout.status === "ready" ? objectIds(layout.value, events) : null;
  // An actor or target that is an object of the world can be selected; any other id is just text in a box of the
  // same size, so the layout arriving moves nothing (CLS).
  const pick = (id: string) =>
    ids?.has(id) ? (
      <button
        type="button"
        className="park-view-pick"
        data-lens-control
        aria-pressed={selected === id}
        onClick={() => toggle(id)}
      >
        {id}
      </button>
    ) : (
      <span className="park-view-pickbox">{id}</span>
    );
  return (
    <LensFrame worldId={worldId} current="trace" title="Trace">
      <div data-testid="trace-lens" className="park-view-body">
        <p className="park-view-note">
          The raw record viewer is not built yet: a record is named here, not opened.
        </p>
        {events.length === 0 ? (
          <p className="park-view-note">
            Nothing recorded yet. Each event gets a row here as it arrives.
          </p>
        ) : (
          <ol className="park-view-trace" aria-label="Every recorded event, in order">
            {events.map((e) => {
              const t = e.trace;
              const call = [
                t.model_role,
                t.tokens_in !== null && t.tokens_out !== null
                  ? `${t.tokens_in} in, ${t.tokens_out} out`
                  : null,
                t.latency_ms !== null ? `${t.latency_ms} ms` : null,
              ].filter((part) => part !== null);
              return (
                <li
                  key={e.seq}
                  data-testid="trace-lens-row"
                  data-event-type={e.type}
                  data-seq={e.seq}
                  data-selected={selected !== null && involves(e, selected)}
                >
                  <div className="park-view-tracetop">
                    <span className="park-view-seq">{e.seq}</span>
                    <span className="park-view-time">{elapsed(events, e)}</span>
                    <b>{e.type}</b>
                    {isKnownType(e.type) ? null : (
                      <span className="park-view-flag park-view-flag--info">
                        Not in the registry
                      </span>
                    )}
                  </div>
                  <div className="park-view-tracemeta">
                    <span>
                      {pick(e.actor)} → {pick(e.target)}
                    </span>
                    {call.length > 0 ? <span>{call.join(" · ")}</span> : null}
                    <span>
                      {e.credits} {e.credits === 1 ? "credit" : "credits"}
                    </span>
                    {t.archive_ref === null ? (
                      <span>No record</span>
                    ) : (
                      <span>
                        Record <code>{t.archive_ref}</code>
                      </span>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </LensFrame>
  );
}
