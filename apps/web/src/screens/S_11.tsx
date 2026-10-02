// S-11 Trace lens with archive links (PRD 18.3, 9.6): every recorded event as a row, including
// types the registry does not know (HR-5 puts those here and nowhere else). Columns are the
// event's own `trace` block. The raw-record viewer is not built: its control is a placeholder.
import { useClient } from "../api/ClientProvider";
import { elapsed, useRunLog } from "../world/runLog";
import { isKnownType } from "../world/registry";
import { LensTabs } from "./LensTabs";
import { Placeholder } from "./Placeholder";
import type { ScreenProps } from "./routes";

const dash = (v: string | number | null): string => (v === null ? "none" : String(v));

export function S_11({ params }: ScreenProps) {
  const worldId = params[0] ?? "";
  const events = useRunLog(useClient(), worldId);
  return (
    <div className="screen-body wide" data-testid="trace-lens">
      <LensTabs worldId={worldId} current="trace" />
      <h1>Trace</h1>
      {events.length === 0 ? (
        <p>Nothing recorded yet. Each event gets a row here as it arrives.</p>
      ) : (
        // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable region must be keyboard reachable (WCAG 2.1.1).
        <section className="trace-scroll" aria-label="Trace table" tabIndex={0}>
          <table className="screen-table trace-table">
            <thead>
              <tr>
                {[
                  "Seq",
                  "Time",
                  "Event",
                  "Actor",
                  "Target",
                  "Model role",
                  "Tokens in/out",
                  "Latency",
                  "Credits",
                  "Record",
                ].map((h) => (
                  <th key={h} scope="col">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.seq} data-testid="trace-lens-row" data-event-type={e.type}>
                  <td>{e.seq}</td>
                  <td>{elapsed(events, e)}</td>
                  <td>
                    {e.type}
                    {!isKnownType(e.type) && <b> (not in the registry)</b>}
                  </td>
                  <td>{e.actor}</td>
                  <td>{e.target}</td>
                  <td>{dash(e.trace.model_role)}</td>
                  <td>
                    {dash(e.trace.tokens_in)} / {dash(e.trace.tokens_out)}
                  </td>
                  <td>{e.trace.latency_ms === null ? "none" : `${e.trace.latency_ms} ms`}</td>
                  <td>{e.credits}</td>
                  <td>
                    {e.trace.archive_ref === null ? (
                      "none"
                    ) : (
                      <>
                        <code>{e.trace.archive_ref}</code> <Placeholder label="Open record" />
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
