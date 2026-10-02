// S-14 Worlds list and replays (PRD 18.3, HR-4). The one world the client knows: title, state and
// credits from the recorded events, size from the layout. The run is a recording, so the card says
// "Replay of run ... recorded ..." (HR-4). Layout after design/source "Tilo Worlds.dc.html": title,
// primary "New task" top right, filters, world cards with a state pill, progress and a footer.
// Filters are placeholders.
import { useClient } from "../api/ClientProvider";
import { creditsUsed } from "../world/runLog";
import { AppLink } from "./AppLink";
import { Loaded, Primary } from "./FlowShell";
import { Chip, Page, Section, Soon, field, longDate, useFixtureRun, words } from "./kit";
import { useAction, useRemote } from "./remote";

export function S_14() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const [layout, retry] = useRemote("load the worlds", () => client.getLayout(worldId));
  const newTask = useAction("start a new task", async () => "/");
  const first = events[0];
  const done = events.at(-1)?.type === "world.completed";
  const granted = events.find((e) => e.type === "budget.granted");
  const cap = granted ? Number(field(granted, "cap")) : 0;
  const used = creditsUsed(events);
  const w = `/world/${encodeURIComponent(worldId)}`;
  return (
    <Page
      testid="worlds"
      title="Worlds list and replays"
      sub="Every job Tilo is running, has scheduled or has finished for you."
      action={<Primary label="New task" action={newTask} />}
    >
      <Soon labels={["Search worlds", "Filter by status"]} />
      <Section title="Your worlds" reserve={[13, 14]}>
        <Loaded what="the worlds" remote={layout} retry={retry} isEmpty={() => false}>
          {(l) => (
            <article className="world-card" data-testid="world-card">
              <div className="card-top">
                <Chip tone="fyi">{words(l.tier)}</Chip>
                <Chip tone={done ? "done" : "needs"}>{done ? "Finished" : "Replaying"}</Chip>
              </div>
              <h3>{first ? String(field(first, "title")) : "Loading the recording"}</h3>
              <p className="row-sub">
                {l.semantic.levels.length} level(s) · {l.semantic.agents.length} agents
              </p>
              <progress
                max={cap > 0 ? cap : 1}
                value={used}
                aria-label="Credits used of the approved budget"
              />
              <p className="card-foot">
                <span>{cap > 0 ? `${used} of ${cap} credits` : `${used} credits`}</span>
                <span>{first ? `Recorded ${longDate(first.ts)}` : "Not started"}</span>
              </p>
              <p className="row-sub" data-testid="replay-note">
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
            </article>
          )}
        </Loaded>
      </Section>
    </Page>
  );
}
