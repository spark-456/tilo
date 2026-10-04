// S-11 Trace lens with archive links (PRD 18.3, 9.6): every recorded event as a two-line row, the
// type on top and below it actor to target, the model call, credits and the archive record, so the
// record is always in view (no sideways scroll). Unregistered types are listed too and marked:
// HR-5 puts them here and nowhere else. The raw-record viewer is not built, so its control is a
// placeholder. Layout after the Trace lens of design/source "Tilo World Player.dc.html".
import { useClient } from "../api/ClientProvider";
import { isKnownType } from "../world/registry";
import { elapsed, useRunLog } from "../world/runLog";
import { involves, objectIds, useSelection } from "../world/selection";
import { LensTabs } from "./LensTabs";
import { Placeholder } from "./Placeholder";
import { useRemote } from "./remote";
import type { ScreenProps } from "./routes";

export function S_11({ params }: ScreenProps) {
  const worldId = params[0] ?? "";
  const client = useClient();
  const events = useRunLog(client, worldId);
  const [selected, , toggle] = useSelection(worldId);
  const [layout] = useRemote("load the world", () => client.getLayout(worldId));
  const ids = layout.status === "ready" ? objectIds(layout.value, events) : null;
  // An actor or target that is an object of the world can be selected; any other id is just text
  // in a box of the same size, so the layout arriving moves nothing (CLS).
  const pick = (id: string) =>
    ids?.has(id) ? (
      <button
        type="button"
        className="pick"
        data-lens-control
        aria-pressed={selected === id}
        onClick={() => toggle(id)}
      >
        {id}
      </button>
    ) : (
      <span className="pick-box">{id}</span>
    );
  return (
    <div className="screen-body wide" data-testid="trace-lens">
      <LensTabs worldId={worldId} current="trace" />
      <h1>Trace</h1>
      <p className="screen-tag">Opening a raw record is coming soon.</p>
      {events.length === 0 ? (
        <p>Nothing recorded yet. Each event gets a row here as it arrives.</p>
      ) : (
        <ol className="trace-rows" aria-label="Every recorded event, in order">
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
                <div className="trace-top">
                  <span className="trace-seq">{e.seq}</span>
                  <span className="trace-time">{elapsed(events, e)}</span>
                  <b>{e.type}</b>
                  {!isKnownType(e.type) && <span className="chip">Not in the registry</span>}
                </div>
                <div className="trace-meta">
                  <span>
                    {pick(e.actor)} → {pick(e.target)}
                  </span>
                  {call.length > 0 && <span>{call.join(" · ")}</span>}
                  <span>
                    {e.credits} {e.credits === 1 ? "credit" : "credits"}
                  </span>
                  {t.archive_ref === null ? (
                    <span>No record</span>
                  ) : (
                    <span className="trace-record">
                      <code>{t.archive_ref}</code> <Placeholder compact label="Open record" />
                    </span>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
