// S-10 Story lens (PRD 18.3, 9.6): the run as plain sentences, one per recorded event, taken from
// the event's own `summary`. Registered types only (HR-5: unknown types appear in the Trace).
// Layout after design/source "Tilo 2 Balanced Refined.dc.html" 2-1 and "Tilo World Player.dc.html".
import type { Severity } from "@tilo/contracts";
import { useClient, useIsFixtureClient } from "../api/ClientProvider";
import { isKnownType } from "../world/registry";
import { useReplayedLog } from "../world/replay";
import { elapsed } from "../world/runLog";
import { agentNames, worldStatus } from "../world/runSummary";
import { involves, useSelection } from "../world/selection";
import { LensTabs } from "./LensTabs";
import { useRemote } from "./remote";
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
  const { events } = useReplayedLog(client, worldId);
  const fixture = useIsFixtureClient();
  const status = worldStatus(events);
  const story = events.filter((e) => isKnownType(e.type));
  const [selected, , toggle] = useSelection(worldId);
  const [layout] = useRemote("load the world", (signal) => client.getLayout(worldId, signal));
  const names = layout.status === "ready" ? agentNames(layout.value) : null;
  // The rows wait for the layout (ready or failed) so the who-chips never arrive after them and
  // push the text about (CLS); a failed layout still shows the story, without chips.
  const settled = layout.status !== "loading";
  return (
    <div className="screen-body wide" data-testid="story-lens">
      <LensTabs worldId={worldId} current="story" />
      <h1>Story</h1>
      {fixture && (
        <p className="screen-tag replay-tip">
          {status === "failed"
            ? "The recorded run stopped with an error."
            : status === "completed"
              ? "The recorded fixture replay has finished."
              : `Replaying the recorded fixture: ${story.length} events so far.`}
        </p>
      )}
      {!settled ? (
        <p>Loading the story…</p>
      ) : story.length === 0 ? (
        <p>Nothing has happened yet. The story fills in as events arrive.</p>
      ) : (
        <div role="log" aria-label="What happened, in order">
          <ol className="story-list">
            {story.map((e) => (
              <li
                key={e.seq}
                data-seq={e.seq}
                data-severity={e.severity}
                data-selected={selected !== null && involves(e, selected)}
              >
                <span className="story-time">{elapsed(events, e)}</span>
                <span>
                  {e.summary}
                  {SEVERITY_LABEL[e.severity] && (
                    <b className="story-flag"> · {SEVERITY_LABEL[e.severity]}</b>
                  )}{" "}
                  {names?.has(e.actor) && (
                    <button
                      type="button"
                      className="pick"
                      data-lens-control
                      aria-pressed={selected === e.actor}
                      onClick={() => toggle(e.actor)}
                    >
                      {names.get(e.actor)}
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
