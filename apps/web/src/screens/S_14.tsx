// S-14 Worlds list and replays (PRD 18.3, HR-4). The one world the client knows: title, state and
// credits from the recorded events, size and levels from the layout, work done from the reducer.
// The run is a recording, so the card says "Replay of run ... recorded ..." (HR-4). Layout after
// design/source "Tilo Worlds.dc.html": title, primary "New task" top right, a search field and
// status filters with counts, then world cards with a thumbnail, a size tag and a state pill on it,
// a title, progress and a footer. Search and filters work on the worlds the client has, and every
// count is computed from them: nothing is scheduled in this build, so Scheduled says 0.
import { useId, useRef, useState } from "react";
import { useClient, useWorldKnown } from "../api/ClientProvider";
import { deriveQueue } from "../needs-you/queue";
import { reduce } from "../world/reducer";
import { creditsUsed, useRunLog } from "../world/runLog";
import { budgetCap, worldStatus } from "../world/runSummary";
import { alsoWorld, useAddressedWorld, useRunWorld, withWorld } from "../world/worldContext";
import { AppLink } from "./AppLink";
import { Loaded, Primary } from "./FlowShell";
import { NotFound } from "./NotFound";
import { WorldThumb } from "./WorldThumb";
import { Chip, EmptyState, Page, field, longDate, plural, words } from "./kit";
import { useAction, useRemote } from "./remote";
import {
  FILTERS,
  FILTER_LABEL,
  type Filter,
  SIZES,
  SIZE_LABEL,
  type Size,
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
  const worldId = useRunWorld(); // null: a live API and no run started
  const addressed = useAddressedWorld();
  const events = useRunLog(client, worldId);
  const worldKnown = useWorldKnown(worldId);
  const known = worldId !== null && worldKnown; // false: the client has no world to list
  const [layout, retry] = useRemote(
    "load the worlds",
    (signal) => client.getLayout(worldId ?? "", signal),
    known, // no run: nothing is asked of the API
  );
  const newTask = useAction("start a new task", async () => "/");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [sizeFilter, setSizeFilter] = useState<Size>("all");
  // On a phone the size chips sit behind a Filters button and open as a panel over the list (no
  // shift); from 768 px up they are always shown and the button is hidden.
  const [sizesOpen, setSizesOpen] = useState(false);
  const sizesId = useId();
  const toggle = useRef<HTMLButtonElement>(null);
  const closeSizes = () => {
    setSizesOpen(false);
    toggle.current?.focus();
  };
  if (addressed !== null && !worldKnown) return <NotFound />; // a world the client does not know
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
  const queue = deriveQueue(events);
  const waiting = queue.length;
  const next = queue[0];
  const title = first ? String(field(first, "title")) : "Waiting for the recording";
  const size = layout.status === "ready" ? layout.value.tier : null;
  const worlds: readonly WorldRow[] = known ? [{ title, phase, waiting, size }] : [];
  const counts = countsOf(worlds, query, sizeFilter);
  const shown = visible(worlds, filter, query, sizeFilter);
  const cap = budgetCap(events);
  const used = creditsUsed(events);
  const w = `/world/${encodeURIComponent(worldId ?? "")}`;
  return (
    <Page
      testid="worlds"
      title="Worlds"
      sub="Every job Tilo is running, has scheduled or has finished for you."
      action={<Primary label="New task" action={newTask} />}
    >
      <div
        className="filter-bar"
        onKeyDown={(e) => {
          if (e.key === "Escape" && sizesOpen) closeSizes();
        }}
      >
        <fieldset className="filter-chips status-tabs">
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
        <label className="search-field">
          <span className="visually-hidden">Search worlds</span>
          <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">
            <circle cx="8.5" cy="8.5" r="5.5" fill="none" stroke="currentColor" strokeWidth="2" />
            <path d="M13 13l4.5 4.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <input
            type="search"
            value={query}
            placeholder="Search worlds"
            autoComplete="off"
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <button
          ref={toggle}
          type="button"
          className="size-toggle"
          data-filter-control
          aria-expanded={sizesOpen}
          aria-controls={sizesId}
          onClick={() => setSizesOpen(!sizesOpen)}
        >
          Filters: {SIZE_LABEL[sizeFilter]}
        </button>
        <fieldset id={sizesId} className="filter-chips size-chips" data-open={sizesOpen}>
          <legend className="visually-hidden">Filter by size</legend>
          {SIZES.map((s) => (
            <label key={s} className="filter-chip">
              <input
                type="radio"
                name="worlds-size"
                value={s}
                checked={sizeFilter === s}
                onChange={() => {
                  setSizeFilter(s);
                  if (sizesOpen) closeSizes();
                }}
              />
              <span>{SIZE_LABEL[s]}</span>
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
                  : sizeFilter !== "all"
                    ? `No ${SIZE_LABEL[sizeFilter].toLowerCase()} world here. Pick All sizes to see every world.`
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
                <article
                  className="world-card"
                  data-testid="world-card"
                  data-tier={l.tier}
                  data-needs={waiting > 0}
                >
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
                    <div className="world-progress">
                      <progress max={levels} value={done} aria-label="Levels finished" />
                      <span aria-hidden="true">{`${Math.round((done / Math.max(levels, 1)) * 100)}%`}</span>
                    </div>
                    <p className="card-foot">
                      <span>
                        {cap === null ? `${used} credits used` : `${used} of ${cap} credits used`}
                      </span>
                      <span>{first ? longDate(first.ts) : "Not started"}</span>
                    </p>
                    <div
                      className="world-decision"
                      data-testid="world-needs"
                      data-tone={next ? "needs" : "clear"}
                    >
                      {next ? (
                        <>
                          <p className="decision-head">
                            {plural(waiting, "decision")} waiting for you
                          </p>
                          <p className="bitem-sub">{next.opened.summary}</p>
                          <AppLink
                            to={
                              next.kind === "gate"
                                ? alsoWorld(
                                    `/needs-you/gate?run=${encodeURIComponent(next.runId)}&gate=${encodeURIComponent(next.gateId ?? "")}`,
                                    worldId ?? "",
                                  )
                                : withWorld("/needs-you", worldId ?? "")
                            }
                            className="pill"
                          >
                            {next.kind === "gate" ? "Review the gate" : "Open Needs you"}
                          </AppLink>
                        </>
                      ) : (
                        <p className="decision-head">Nothing waits for you.</p>
                      )}
                    </div>
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
        )}
      </div>
    </Page>
  );
}
