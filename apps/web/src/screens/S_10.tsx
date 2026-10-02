// S-10 Story lens (PRD 18.3, 9.6): the run as plain sentences, one per recorded event, taken from
// the event's own `summary`. Registered types only (HR-5: unknown types appear in the Trace).
// Layout after design/source "Tilo 2 Balanced Refined.dc.html" 2-1 and "Tilo World Player.dc.html".
import type { Severity } from "@tilo/contracts";
import { useClient, useIsFixtureClient } from "../api/ClientProvider";
import { elapsed, useRunLog } from "../world/runLog";
import { isKnownType } from "../world/registry";
import { LensTabs } from "./LensTabs";
import type { ScreenProps } from "./routes";

/** A text label for every severity that is not routine, so colour never carries it alone. */
export const SEVERITY_LABEL: Partial<Record<Severity, string>> = {
  fyi: "FYI",
  nudge: "Reminder",
  needs_you: "Needs you",
  blocked: "Blocked",
  gate: "Approval",
};

export function S_10({ params }: ScreenProps) {
  const worldId = params[0] ?? "";
  const client = useClient();
  const events = useRunLog(client, worldId);
  const replaying = useIsFixtureClient() && events.at(-1)?.type !== "world.completed";
  const story = events.filter((e) => isKnownType(e.type));
  return (
    <div className="screen-body wide" data-testid="story-lens">
      <LensTabs worldId={worldId} current="story" />
      <h1>Story</h1>
      {story.length === 0 ? (
        <p>Nothing has happened yet. The story fills in as events arrive.</p>
      ) : (
        <div role="log" aria-label="What happened, in order">
          <ol className="story-list">
            {story.map((e) => (
              <li key={e.seq} data-seq={e.seq} data-severity={e.severity}>
                <span className="story-time">{elapsed(events, e)}</span>
                <span>
                  {e.summary}
                  {SEVERITY_LABEL[e.severity] && (
                    <b className="story-flag"> · {SEVERITY_LABEL[e.severity]}</b>
                  )}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
      {replaying && (
        <p className="screen-tag">
          Replaying the recorded fixture at its own pace ({story.length} events so far). Add{" "}
          <code>?speed=20</code> to the address to fast-forward.
        </p>
      )}
    </div>
  );
}
