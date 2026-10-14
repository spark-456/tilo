// The stage's side panels (PRD 18.3 S-04): the live meter, Pause all, the needs-you count, the team, the levels and
// the gates. Every figure is derived from the recorded events (HR-1); before the first event nothing shows a figure
// (UX-3, HR-2). A column beside the stage on a wide screen, a collapsible block under it on a phone.
import type { Event, Layout } from "@tilo/contracts";
import { type ReactNode, useMemo } from "react";
import { useClient } from "../api/ClientProvider";
import { useRemote } from "../park/shared/remote";
import { buildingCount, levelRows } from "../world/levels";
import { type PauseView, usePause } from "../world/pause";
import { reduce } from "../world/reducer";
import { useReplayedLog } from "../world/replay";
import { creditsUsed, useRunStatus, waitingForYou } from "../world/runLog";
import {
  BUILDING_STATE,
  RUN_STATUS_LABEL,
  type RunStatus,
  agentNames,
  budgetCap,
  hudGlance,
  memorySaved,
  rankName,
  worldStatus,
} from "../world/runSummary";
import { useSelection } from "../world/selection";
import { withWorld } from "../world/worldContext";
import { ViewLink } from "./ViewLink";
import { inspectPath } from "./routes";
import { plural, words } from "./text";

/** One outline row: a toggle button that selects its object for every lens (FR-WLD-06). Rows keep the same box
 * selected or not (the mark is an outline), so choosing one moves nothing. */
function Pick({
  id,
  selected,
  toggle,
  children,
}: { id: string; selected: string | null; toggle: (id: string) => void; children: ReactNode }) {
  return (
    <button
      type="button"
      className="park-view-row"
      data-lens-control
      aria-pressed={selected === id}
      onClick={() => toggle(id)}
    >
      {children}
    </button>
  );
}

const NOTE: Record<PauseView, string> = {
  ready: "Stops every agent.",
  pausing: "Pausing…",
  unconfirmed: "No confirmation recorded yet. Agents may still be working. You can try again.",
  error: "",
  unavailable: "Coming soon: this connection cannot pause yet.",
  paused: "All work is paused.",
  ended: "This run has ended.",
};
const REPLAY_NOTE = "A recorded replay cannot be paused.";

/** FR-WLD-07: the Pause all control and the "Paused" banner, one fixed-height slot. Pause all is a request: only a
 * recorded world.paused shows "Paused" (HR-1). Resume has no client call yet, so it is an aria-disabled control. */
function PauseSlot({
  view,
  note,
  onPause,
}: { view: PauseView; note: string; onPause: () => void }) {
  const blocked =
    view === "pausing" || view === "unavailable" || view === "paused" || view === "ended";
  return (
    <section
      className="park-view-card park-view-pause"
      aria-label="Pause all"
      data-testid="pause-slot"
      data-pause={view}
    >
      <div className="park-view-pauserow">
        <button
          type="button"
          className="park-view-chiplink"
          data-testid="pause-all"
          data-pause-control
          aria-disabled={blocked ? "true" : undefined}
          aria-busy={view === "pausing" ? "true" : undefined}
          title={view === "unavailable" ? note : undefined}
          onClick={() => {
            if (!blocked) onPause();
          }}
        >
          Pause all
        </button>
        {view === "paused" ? (
          <button
            type="button"
            className="park-view-chiplink"
            data-testid="resume"
            aria-disabled="true"
            title="Coming soon"
            onClick={(e) => e.preventDefault()}
          >
            Resume
          </button>
        ) : null}
      </div>
      {/* biome-ignore lint/a11y/useSemanticElements: a live status region, not a form result. */}
      <p className="park-view-pausenote" role="status">
        {note}
      </p>
    </section>
  );
}

export function WorldPauseSlot({ worldId, confirmMs }: { worldId: string; confirmMs?: number }) {
  const client = useClient();
  const status = useRunStatus(client, worldId);
  const { view, error, pause } = usePause(client, worldId, status, confirmMs);
  return (
    <PauseSlot view={view} note={view === "error" ? (error ?? "") : NOTE[view]} onPause={pause} />
  );
}

/** The slot beside a recorded replay (?fixture=): no client runs it, so it cannot be paused, but a world.paused
 * recorded in the stream still shows Paused. */
export function ReplayPauseSlot({ status }: { status: RunStatus }) {
  const view: PauseView =
    status === "paused"
      ? "paused"
      : status === "completed" || status === "failed"
        ? "ended"
        : "unavailable";
  return (
    <PauseSlot
      view={view}
      note={view === "unavailable" ? REPLAY_NOTE : NOTE[view]}
      onPause={() => undefined}
    />
  );
}

/** The phone's collapsed World status line: the HUD at a glance, from the same replayed events as the panels it
 * opens (a fixed one-line box: new words never move the sheet, CLS). */
export function HudGlance({
  worldId,
  replayed = null,
}: { worldId: string; replayed?: readonly Event[] | null }) {
  const log = useReplayedLog(useClient(), worldId);
  const events = replayed ?? log.events;
  return (
    <span className="park-view-glance" data-testid="hud-glance">
      {hudGlance(worldStatus(events), events, creditsUsed(events), waitingForYou(events))}
    </span>
  );
}

/** `replayed`: the events of a ?fixture= replay up to the stage's seq; they replace the client's own log of the
 * same world, which may not have started (HR-1: one run on screen, one story). */
export function StageRail({
  worldId,
  replayed = null,
  pauseStatus = null,
  compact = false,
}: {
  worldId: string;
  replayed?: readonly Event[] | null;
  /** A replay's recorded status: it has no client to pause. */
  pauseStatus?: RunStatus | null;
  /** Presentation keeps the meter, pause and Needs-you controls without the object lists. */
  compact?: boolean;
}) {
  const client = useClient();
  const log = useReplayedLog(client, worldId);
  const events = replayed ?? log.events;
  const [selected, , toggle] = useSelection(worldId);
  const [layoutRemote] = useRemote("load the world", (signal) => client.getLayout(worldId, signal));
  const status = worldStatus(events);
  // The delivery exists only once world.completed is recorded: asking before that is a refusal the browser logs as
  // an error, so the run's own events say when to ask.
  const [deliveryRemote] = useRemote(
    "load the delivery",
    () => client.getDelivery(worldId),
    status === "completed",
  );
  const layout: Layout | null = layoutRemote.status === "ready" ? layoutRemote.value : null;
  const state = useMemo(() => (layout ? reduce(layout, events) : null), [layout, events]);
  const names = layout ? agentNames(layout) : null;
  const acted = new Set(events.map((e) => e.actor));
  const cap = budgetCap(events);
  const waiting = waitingForYou(events);
  const saved =
    status === "completed" && deliveryRemote.status === "ready"
      ? deliveryRemote.value.time_saved
      : null;
  const levels = layout && state ? levelRows(layout, state, events) : [];
  return (
    <div className="park-view-rail" data-testid="world-hud">
      <section className="park-view-card" aria-label="Live meter" data-testid="hud-meter">
        {events.length === 0 ? (
          <p className="park-view-note">Nothing yet. This fills in once a run starts.</p>
        ) : (
          <>
            <span className="park-view-flag park-view-flag--info">{RUN_STATUS_LABEL[status]}</span>
            {status === "idle" ? (
              // No world.* event yet: words, not a "0" figure, beside a screen that may already show a finished
              // run.
              <p className="park-view-note">The run has not started. No credits used yet.</p>
            ) : (
              <div className="park-view-figures">
                <div>
                  <b>{creditsUsed(events)}</b>
                  <span>{cap === null ? "credits used" : `credits of ${cap} approved`}</span>
                </div>
                <div>
                  <b>{saved ? `${saved.low_min} to ${saved.high_min} min` : "Not yet"}</b>
                  <span>saved · estimate</span>
                </div>
                <div data-testid="memory-saved">
                  <b>{memorySaved(events)}</b>
                  <span>credits saved by memory</span>
                </div>
                {saved ? (
                  <ViewLink className="park-view-chiplink" to="/settings?section=estimate">
                    How we estimate
                  </ViewLink>
                ) : null}
              </div>
            )}
          </>
        )}
      </section>
      {pauseStatus !== null ? (
        <ReplayPauseSlot status={pauseStatus} />
      ) : (
        <WorldPauseSlot worldId={worldId} />
      )}
      <div className="park-view-count">
        <h2 className="park-view-h2">Needs you</h2>
        {waiting > 0 ? (
          <ViewLink className="park-view-chiplink" to={withWorld("/needs-you", worldId)}>
            Open the queue
          </ViewLink>
        ) : null}
        <span
          className={`park-view-flag park-view-flag--${waiting > 0 ? "needs" : "info"}`}
          data-testid="needs-count"
        >
          {waiting}
        </span>
      </div>
      {compact ? null : (
        <div className="park-view-slot" data-testid="stage-rail-details">
          {layout === null || names === null ? (
            <>
              <h2 className="park-view-h2">Team</h2>
              <p className="park-view-note">
                {layoutRemote.status === "error" ? layoutRemote.message : "The team is loading…"}
              </p>
            </>
          ) : (
            <>
              <h2 className="park-view-h2">Team</h2>
              <ul className="park-view-rows">
                {layout.semantic.agents.map((a) => (
                  <li key={a.id}>
                    <Pick id={a.id} selected={selected} toggle={toggle}>
                      <span className="park-view-rowname">{names.get(a.id)}</span>
                      <span className="park-view-rowstate">
                        {state?.agents[a.id]?.spawned || acted.has(a.id)
                          ? "Joined"
                          : "Not joined yet"}
                      </span>
                    </Pick>
                  </li>
                ))}
              </ul>
              <p className="park-view-counts">
                {words(layout.tier)} · {plural(layout.semantic.agents.length, "agent")} ·{" "}
                {plural(buildingCount(layout), "building")} ·{" "}
                {plural(layout.semantic.gates.length, "gate")}
              </p>
              {layout.semantic.levels.map((level) => {
                const row = levels.find((r) => r.id === level.id);
                return (
                  <section key={level.id}>
                    <h2 className="park-view-h2">
                      <ViewLink to={inspectPath(worldId, level.id)}>Level {level.name}</ViewLink>
                      {row ? (
                        <span className="park-view-pct">
                          {" "}
                          {row.percent}%
                          <progress
                            max={100}
                            value={row.percent}
                            aria-label={`${row.name}: buildings finished`}
                          />
                        </span>
                      ) : null}
                    </h2>
                    {row?.line ? <p className="park-view-note">{row.line}</p> : null}
                    <ul className="park-view-rows">
                      {level.districts.flatMap((d) =>
                        d.buildings.map((b) => (
                          <li key={b.id}>
                            <Pick id={b.id} selected={selected} toggle={toggle}>
                              <span className="park-view-rowname">
                                {b.name}
                                <small>{d.name}</small>
                              </span>
                              <span className="park-view-rowstate">
                                {BUILDING_STATE[state?.buildings[b.id]?.status ?? "hidden"]}
                              </span>
                            </Pick>
                          </li>
                        )),
                      )}
                    </ul>
                  </section>
                );
              })}
              {layout.semantic.gates.length > 0 ? (
                <section>
                  <h2 className="park-view-h2">Gates</h2>
                  <ul className="park-view-rows">
                    {layout.semantic.gates.map((g) => (
                      <li key={g.id}>
                        <Pick id={g.id} selected={selected} toggle={toggle}>
                          <span className="park-view-rowname">
                            Gate {g.id}
                            <small>{rankName(g.guards)}</small>
                          </span>
                          <span className="park-view-rowstate">Approval gate</span>
                        </Pick>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </>
          )}
        </div>
      )}
    </div>
  );
}
