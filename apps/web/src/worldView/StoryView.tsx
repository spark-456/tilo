// The Story lens (PRD 18.3, 9.6): the run as plain sentences, one per recorded event, from the event's own `summary`.
// Registered types only (HR-5: unknown types appear in the Trace).
import type { Severity } from "@tilo/contracts";
import { useClient, useIsFixtureClient } from "../api/ClientProvider";
import { useRemote } from "../screens/remote";
import { isKnownType } from "../world/registry";
import { useReplayPoint, useReplayedLog } from "../world/replay";
import { elapsed, useRunLog } from "../world/runLog";
import { agentNames, runEnded, worldStatus } from "../world/runSummary";
import { involves, useSelection } from "../world/selection";
import { LensFrame } from "./LensFrame";
import { LevelChip, levelOf } from "./LevelChip";
import { useStoryAnnouncement } from "./storyAnnounce";

/** A text label for every severity that is not routine, so colour never carries it alone. */
export const SEVERITY_LABEL: Partial<Record<Severity, string>> = {
  fyi: "FYI",
  nudge: "Reminder",
  needs_you: "Needs you",
  blocked: "Blocked",
  gate: "Approval",
};

const SEVERITY_TONE: Partial<Record<Severity, string>> = {
  fyi: "info",
  nudge: "info",
  needs_you: "needs",
  blocked: "blocked",
  gate: "gate",
};

export function StoryView({ worldId }: { worldId: string }) {
  const client = useClient();
  const { events } = useReplayedLog(client, worldId);
  const fixture = useIsFixtureClient();
  const status = worldStatus(events);
  const story = events.filter((e) => isKnownType(e.type));
  const [selected, , toggle] = useSelection(worldId);
  const [layout] = useRemote("load the world", (signal) => client.getLayout(worldId, signal));
  const names = layout.status === "ready" ? agentNames(layout.value) : null;
  // The rows wait for the layout (ready or failed) so the who-chips never arrive after them and push the text
  // about (CLS); a failed layout still shows the story, without chips.
  const settled = layout.status !== "loading";
  // Only events that arrive live are news. A fixture, a scrubbed moment and a run that has ended are replays of
  // what is already recorded, so none of them announces.
  const replayPoint = useReplayPoint(worldId);
  const ended = runEnded(worldStatus(useRunLog(client, worldId)));
  const announced = useStoryAnnouncement(
    story,
    settled && !fixture && replayPoint === null && !ended,
  );
  return (
    <LensFrame worldId={worldId} current="story" title="Story">
      <div data-testid="story-lens" className="park-view-body">
        {fixture ? (
          <p className="park-view-note">
            {status === "failed"
              ? "The recorded run stopped with an error."
              : status === "completed"
                ? "The recorded replay has finished."
                : `Replaying the recorded run: ${story.length} events so far.`}
          </p>
        ) : null}
        {!settled ? (
          <p className="park-view-note">Loading the story…</p>
        ) : story.length === 0 ? (
          <p className="park-view-note">
            Nothing has happened yet. The story fills in as events arrive.
          </p>
        ) : (
          <div>
            <output className="sr-only" aria-live="polite" aria-atomic="true">
              {announced}
            </output>
            <ol className="park-view-story" aria-label="What happened, in order">
              {story.map((e) => {
                const lv = levelOf(layout.status === "ready" ? layout.value : null, e);
                const flag = SEVERITY_LABEL[e.severity];
                return (
                  <li
                    key={e.seq}
                    data-seq={e.seq}
                    data-severity={e.severity}
                    data-selected={selected !== null && involves(e, selected)}
                  >
                    <span className="park-view-time">{elapsed(events, e)}</span>
                    <div className="park-view-storybody">
                      <p className="park-view-text">{e.summary}</p>
                      {lv || flag || names?.has(e.actor) ? (
                        <p className="park-view-meta">
                          {lv ? <LevelChip level={lv} /> : null}
                          {flag ? (
                            <span
                              className={`park-view-flag park-view-flag--${SEVERITY_TONE[e.severity] ?? "info"}`}
                            >
                              {flag}
                            </span>
                          ) : null}
                          {names?.has(e.actor) ? (
                            <button
                              type="button"
                              className="park-view-pick"
                              data-lens-control
                              aria-pressed={selected === e.actor}
                              onClick={() => toggle(e.actor)}
                            >
                              {names.get(e.actor)}
                            </button>
                          ) : null}
                        </p>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ol>
          </div>
        )}
      </div>
    </LensFrame>
  );
}
