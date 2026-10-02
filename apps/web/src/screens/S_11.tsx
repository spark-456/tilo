// S-11 Trace lens with archive links (PRD 18.3, 9.6): every recorded event as a two-line row, the
// type on top and below it actor to target, the model call, credits and the archive record, so the
// record is always in view (no sideways scroll). Unregistered types are listed too and marked:
// HR-5 puts them here and nowhere else. The raw-record viewer is not built, so its control is a
// placeholder. Layout after the Trace lens of design/source "Tilo World Player.dc.html".
import { useClient } from "../api/ClientProvider";
import { isKnownType } from "../world/registry";
import { elapsed, useRunLog } from "../world/runLog";
import { LensTabs } from "./LensTabs";
import { Placeholder } from "./Placeholder";
import type { ScreenProps } from "./routes";

export function S_11({ params }: ScreenProps) {
  const worldId = params[0] ?? "";
  const events = useRunLog(useClient(), worldId);
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
              <li key={e.seq} data-testid="trace-lens-row" data-event-type={e.type}>
                <div className="trace-top">
                  <span className="trace-seq">{e.seq}</span>
                  <span className="trace-time">{elapsed(events, e)}</span>
                  <b>{e.type}</b>
                  {!isKnownType(e.type) && <span className="chip">Not in the registry</span>}
                </div>
                <div className="trace-meta">
                  <span>
                    {e.actor} → {e.target}
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
