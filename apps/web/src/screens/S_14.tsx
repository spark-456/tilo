// S-14 Worlds list and replays (PRD 18.3, HR-4). The one world the client knows: title, state and
// credits from the recorded events, size and levels from the layout, work done from the reducer.
// The run is a recording, so the card says "Replay of run ... recorded ..." (HR-4). Layout after
// design/source "Tilo Worlds.dc.html": title, primary "New task" top right, a filter bar, then
// world cards with a preview, a size tag and a state pill on it, a title, progress and a footer.
// The filters are placeholders. The preview is a static drawing, not the renderer.
import { useClient } from "../api/ClientProvider";
import { reduce } from "../world/reducer";
import { creditsUsed } from "../world/runLog";
import { budgetCap, worldStatus } from "../world/runSummary";
import { AppLink } from "./AppLink";
import { Loaded, Primary } from "./FlowShell";
import { Chip, Page, Soon, field, longDate, plural, useFixtureRun, words } from "./kit";
import { useAction, useRemote } from "./remote";

/** A static isometric block, in neutral role tokens: a thumbnail, not a render of the world. */
function Thumb() {
  return (
    <svg viewBox="0 0 120 90" aria-hidden="true" focusable="false">
      <polygon points="60,10 105,32 60,54 15,32" fill="var(--color-surface-1)" />
      <polygon points="15,32 60,54 60,84 15,62" fill="var(--color-surface-2)" />
      <polygon points="105,32 60,54 60,84 105,62" fill="var(--color-ink-3)" />
      <polygon points="60,24 85,36 60,48 35,36" fill="var(--color-brand-primary)" />
    </svg>
  );
}

const STATUS = {
  idle: ["Recorded", "fyi"],
  active: ["Replaying", "needs"],
  done: ["Finished", "done"],
} as const;

export function S_14() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [layout, retry] = useRemote("load the worlds", (signal) =>
    client.getLayout(worldId, signal),
  );
  const newTask = useAction("start a new task", async () => "/");
  const first = events[0];
  const status = worldStatus(events);
  const [label, tone] =
    events.length === 0 ? STATUS.idle : status === "completed" ? STATUS.done : STATUS.active;
  const cap = budgetCap(events);
  const used = creditsUsed(events);
  const w = `/world/${encodeURIComponent(worldId)}`;
  return (
    <Page
      testid="worlds"
      title="Worlds"
      sub="Every job Tilo is running, has scheduled or has finished for you."
      action={<Primary label="New task" action={newTask} />}
    >
      <Soon className="filter-bar" labels={["Search worlds", "Filter by status"]} />
      <div className="world-grid">
        <Loaded what="the worlds" remote={layout} retry={retry} isEmpty={() => false}>
          {(l) => {
            const levels = l.semantic.levels.length;
            const done = Object.values(reduce(l, events).levels).filter((v) => v.completed).length;
            return (
              <article className="world-card" data-testid="world-card">
                <div className="world-thumb">
                  <Thumb />
                  <Chip tone="fyi">
                    {words(l.tier)} · {plural(levels, "level")}
                  </Chip>
                  <Chip tone={tone}>{label}</Chip>
                </div>
                <div className="world-body">
                  <h2>{first ? String(field(first, "title")) : "Waiting for the recording"}</h2>
                  <p className="bitem-sub">
                    {plural(l.semantic.agents.length, "agent")} on the team · {done} of{" "}
                    {plural(levels, "level")} finished
                  </p>
                  <progress max={levels} value={done} aria-label="Levels finished" />
                  <p className="card-foot">
                    <span>
                      {cap === null ? `${used} credits used` : `${used} of ${cap} credits used`}
                    </span>
                    <span>{first ? longDate(first.ts) : "Not started"}</span>
                  </p>
                  <p className="bitem-sub" data-testid="replay-note">
                    {first
                      ? `Replay of run #${first.run_id.replace(/^r_/, "")} recorded ${longDate(first.ts)}. Nothing here is live.`
                      : "The recorded run has not started playing yet."}
                  </p>
                  <div className="soon-row">
                    <AppLink to={w} className="pill">
                      Open world
                    </AppLink>
                    <AppLink to={`${w}/story`} className="pill">
                      Replay in Story
                    </AppLink>
                  </div>
                </div>
              </article>
            );
          }}
        </Loaded>
      </div>
    </Page>
  );
}
