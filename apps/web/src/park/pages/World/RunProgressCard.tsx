// UI-10 B8: the live run of a real world, read from its recorded events (GET /worlds/{id}/events, polled by the
// client). With no event yet it says so; it never fills in a status, an agent or a step that no event recorded.
import { useState } from "react";
import { Button } from "../../components";
import { isRestartStop, runProgress } from "./runProgress";
import type { RunEvent } from "./useRunEvents";

/** What the card needs to start a stopped run again: the one call, and where the new world is opened. */
export interface StartAgain {
  readonly start: () => Promise<{ readonly worldId: string }>;
  readonly open: (worldId: string) => void;
}

/** RERUN-1: the one honest action for a world a restart stopped. A failure says so and leaves the button for another try. */
function StartItAgain({ again }: { again: StartAgain }) {
  const [state, setState] = useState<"idle" | "busy" | "error">("idle");
  const press = (): void => {
    if (state === "busy") return;
    setState("busy");
    again.start().then(
      (r) => again.open(r.worldId),
      () => setState("error"),
    );
  };
  return (
    <div className="park-world-restart" data-testid="start-it-again">
      <p className="park-world-noruns">
        Tilo restarted while this was running, so it stopped. Nothing more was sent.
      </p>
      <Button variant="primary" onClick={press} aria-busy={state === "busy"}>
        {state === "busy" ? "Starting…" : "Start it again"}
      </Button>
      {state === "error" ? (
        <p className="park-world-noruns" role="alert">
          It could not be started just now. Nothing was started and nothing was charged. Try again
          in a minute.
        </p>
      ) : null}
    </div>
  );
}

export function RunProgressCard({
  events,
  again,
}: { events: readonly RunEvent[]; again?: StartAgain | undefined }) {
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
    ["Buildings", `${p.buildings.done} of ${p.buildings.planned} finished`],
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
      {again && isRestartStop(events) ? <StartItAgain again={again} /> : null}
      <ol className="park-world-teamlist" aria-label="Latest steps">
        {p.steps.map((s) => (
          <li key={s.seq}>
            {s.at ? `${s.at} · ` : ""}
            {s.text}
          </li>
        ))}
      </ol>
    </section>
  );
}
