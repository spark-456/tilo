// S-14 Worlds list and replays (PRD 18.3, HR-4). The one world the client knows: title, state and
// credits from the recorded events, size and levels from the layout, work done from the reducer.
// The run is a recording, so the card says "Replay of run ... recorded ..." (HR-4). Layout after
// design/source "Tilo Worlds.dc.html": title, primary "New task" top right, a search field and
// status filters with counts, then world cards with a thumbnail, a size tag and a state pill on it,
// a title, progress and a footer. Search and filters work on the worlds the client has, and every
// count is computed from them: nothing is scheduled in this build, so Scheduled says 0.
import { useState } from "react";
import { useClient, useWorldKnown } from "../api/ClientProvider";
import { deriveQueue } from "../needs-you/queue";
import { reduce } from "../world/reducer";
import { creditsUsed } from "../world/runLog";
import { budgetCap, worldStatus } from "../world/runSummary";
import { withWorld } from "../world/worldContext";
import { AppLink } from "./AppLink";
import { Loaded, Primary } from "./FlowShell";
import { WorldThumb } from "./WorldThumb";
import { Chip, EmptyState, Page, field, longDate, plural, useFixtureRun, words } from "./kit";
import { useAction, useRemote } from "./remote";
import {
  FILTERS,
  FILTER_LABEL,
  type Filter,
  type WorldPhase,
  type WorldRow,
  countsOf,
  visible,
} from "./worldFilters";

const STATUS: Readonly<Record<WorldPhase, readonly [string, string]>> = {
  recorded: ["Recorded", "fyi"],
  running: ["Replaying", "needs"],
  finished: ["Finished", "done"],
  failed: ["Failed", "blocked"],
};

export function S_14() {
  const client = useClient();
  const { events, worldId } = useFixtureRun();
  const known = useWorldKnown(worldId); // false: the client has no world to list
  const [layout, retry] = useRemote("load the worlds", () => client.getLayout(worldId));
  const newTask = useAction("start a new task", async () => "/");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const first = events[0];
  const status = worldStatus(events);
  const phase: WorldPhase =
    events.length === 0
      ? "recorded"
      : status === "completed"
        ? "finished"
        : status === "failed"
          ? "failed"
          : "running";
  const [label, tone] = STATUS[phase];
  const waiting = deriveQueue(events).length;
  const title = first ? String(field(first, "title")) : "Waiting for the recording";
  const worlds: readonly WorldRow[] = known ? [{ title, phase, waiting }] : [];
  const counts = countsOf(worlds, query);
  const shown = visible(worlds, filter, query);
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
      <div className="filter-bar">
        <label className="search-field">
          <span className="visually-hidden">Search worlds</span>
          <input
            type="search"
            value={query}
            placeholder="Search worlds"
            autoComplete="off"
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <fieldset className="filter-chips">
          <legend className="visually-hidden">Filter by status</legend>
          {FILTERS.map((f) => (
            <label key={f} className="filter-chip">
              <input
                type="radio"
                name="worlds-status"
                value={f}
                checked={filter === f}
                onChange={() => setFilter(f)}
              />
              <span>
                {FILTER_LABEL[f]} <b data-testid={`count-${f}`}>{counts[f]}</b>
              </span>
            </label>
          ))}
        </fieldset>
      </div>
      <div className="world-grid">
        {!known ? (
          <EmptyState
            testid="worlds-empty"
            title="No worlds yet"
            line="Tilo has no world to list yet. Start a task and its world appears here."
            action={{ label: "Start a task", to: "/" }}
          />
        ) : shown.length === 0 ? (
          <EmptyState
            testid="worlds-filter-empty"
            title={
              query.trim() !== ""
                ? "No world matches"
                : `Nothing ${FILTER_LABEL[filter].toLowerCase()}`
            }
            line={
              filter === "scheduled" && query.trim() === ""
                ? "Nothing is scheduled. Worlds that run on a schedule will be listed here."
                : query.trim() !== ""
                  ? "No world matches that search. Clear it or pick All to see every world."
                  : "No world is in this state right now. Pick All to see every world."
            }
          />
        ) : (
          <Loaded what="the worlds" remote={layout} retry={retry} isEmpty={() => false}>
            {(l) => {
              const levels = l.semantic.levels.length;
              const state = reduce(l, events);
              const done = Object.values(state.levels).filter((v) => v.completed).length;
              return (
                <article className="world-card" data-testid="world-card">
                  <div className="world-thumb">
                    <WorldThumb layout={l} state={state} />
                    <Chip tone="fyi">
                      {words(l.tier)} · {plural(levels, "level")}
                    </Chip>
                    <Chip tone={tone}>{label}</Chip>
                  </div>
                  <div className="world-body">
                    <h2>{title}</h2>
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
                    <p className="bitem-sub needs-line" data-testid="world-needs">
                      {waiting > 0 ? (
                        <>
                          {plural(waiting, "decision")} waiting for you.{" "}
                          <AppLink to={withWorld("/needs-you", worldId)}>Open Needs you</AppLink>
                        </>
                      ) : (
                        "Nothing waits for you."
                      )}
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
        )}
      </div>
    </Page>
  );
}
