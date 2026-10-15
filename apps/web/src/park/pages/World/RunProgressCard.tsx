// UI-10 B8: the live run of a real world, read from its recorded events (GET /worlds/{id}/events, polled by the
// client). With no event yet it says so; it never fills in a status, an agent or a step that no event recorded.
import { runProgress } from "./runProgress";
import type { RunEvent } from "./useRunEvents";

export function RunProgressCard({
  events,
  steps = true,
}: {
  events: readonly RunEvent[];
  /** STUDIO-3: false where the Story already lists the recorded steps beside the facts. */
  steps?: boolean;
}) {
  if (events.length === 0) {
    return (
      <section aria-label="Live run" className="park-world-section">
        <div className="park-world-sechead">
          <h2 className="park-world-h2">Live run</h2>
        </div>
        <p className="park-world-noruns">
          No recorded events yet. This fills in as the run records them.
        </p>
      </section>
    );
  }
  const p = runProgress(events);
  const facts: readonly (readonly [string, string])[] = [
    ["Status", p.status],
    ["Agents", String(p.agents)],
    // A run that recorded no building event has no count to show: "0 of 0 finished" would claim a total of nothing.
    ...(p.buildings.planned > 0
      ? ([["Buildings", `${p.buildings.done} of ${p.buildings.planned} finished`]] as const)
      : []),
    ["Credits used", String(p.credits)],
    ["Waiting for you", String(p.waiting)],
  ];
  return (
    <section aria-label="Live run" className="park-world-section">
      <div className="park-world-sechead">
        <h2 className="park-world-h2">Live run</h2>
        <span className="park-world-sub">{`${events.length} recorded events`}</span>
      </div>
      <div className="park-world-facts">
        {facts.map(([k, v]) => (
          <div key={k} className="park-world-fact">
            <span className="park-world-factkey">{k}</span>
            <span className="park-world-factvalue">{v}</span>
          </div>
        ))}
      </div>
      {steps ? (
        <ol className="park-world-teamlist" aria-label="Latest steps">
          {p.steps.map((s) => (
            <li key={s.seq}>
              {s.at ? `${s.at} · ` : ""}
              {s.text}
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
