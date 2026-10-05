// S-04 HUD panels (PRD 18.3), after the "Live meter", needs-you and roster blocks of design/source
// "Tilo 2 Balanced Refined.dc.html" 2-1: hero figures, a needs-you count chip, roster and outline
// rows. Right rail on desktop, bottom sheet on mobile. Every figure is derived from the recorded
// events (HR-1); before the first event nothing shows a figure (UX-3, HR-2).
import type { Event, Layout } from "@tilo/contracts";
import type { ReactNode } from "react";
import { useClient } from "../api/ClientProvider";
import { reduce } from "../world/reducer";
import { useReplayedLog } from "../world/replay";
import { creditsUsed, waitingForYou } from "../world/runLog";
import {
  BUILDING_STATE,
  RUN_STATUS_LABEL,
  agentNames,
  budgetCap,
  hudGlance,
  memorySaved,
  rankName,
  worldStatus,
} from "../world/runSummary";
import { useSelection } from "../world/selection";
import { withWorld } from "../world/worldContext";
import { AppLink } from "./AppLink";
import { LensTabs } from "./LensTabs";
import { WorldPauseSlot } from "./PauseSlot";
import { useRemote } from "./remote";

/** One outline row: a toggle button that selects its object for every lens (FR-WLD-06). Rows keep
 * the same box selected or not (the mark is an outline), so choosing one moves nothing. */
function Pick({
  id,
  selected,
  toggle,
  children,
}: { id: string; selected: string | null; toggle: (id: string) => void; children: ReactNode }) {
  return (
    <button
      type="button"
      className="row"
      data-lens-control
      aria-pressed={selected === id}
      onClick={() => toggle(id)}
    >
      {children}
    </button>
  );
}

/** The phone's collapsed World status line: the HUD at a glance, from the same replayed events as
 * the panels it opens (a fixed one-line box: new words never move the sheet, CLS). */
export function HudGlance({
  worldId,
  replayed = null,
}: { worldId: string; replayed?: readonly Event[] | null }) {
  const log = useReplayedLog(useClient(), worldId);
  const events = replayed ?? log.events;
  return (
    <span className="hud-glance" data-testid="hud-glance">
      {hudGlance(worldStatus(events), events, creditsUsed(events), waitingForYou(events))}
    </span>
  );
}

/** `tabs`: show the lens tabs (S-04 has no page header of its own; the lens screens do). Without
 * them the same height stays reserved, so the rail does not jump between world screens.
 * `replayed`: the events of a ?fixture= replay up to the stage's seq; they replace the client's own
 * log of the same world, which may not have started (HR-1: one run on screen, one story). */
export function WorldPanels({
  worldId,
  tabs = true,
  replayed = null,
}: { worldId: string; tabs?: boolean; replayed?: readonly Event[] | null }) {
  const client = useClient();
  const log = useReplayedLog(client, worldId);
  const events = replayed ?? log.events;
  const [selected, , toggle] = useSelection(worldId);
  const [layoutRemote] = useRemote("load the world", (signal) => client.getLayout(worldId, signal));
  const status = worldStatus(events);
  // The delivery exists only once world.completed is recorded: asking before that is a refusal
  // the browser logs as an error, so the run's own events say when to ask.
  const [deliveryRemote] = useRemote(
    "load the delivery",
    () => client.getDelivery(worldId),
    status === "completed",
  );
  const layout: Layout | null = layoutRemote.status === "ready" ? layoutRemote.value : null;
  const state = layout ? reduce(layout, events) : null;
  const names = layout ? agentNames(layout) : null;
  const acted = new Set(events.map((e) => e.actor));
  const cap = budgetCap(events);
  const waiting = waitingForYou(events);
  const saved =
    status === "completed" && deliveryRemote.status === "ready"
      ? deliveryRemote.value.time_saved
      : null;
  const base = `/world/${encodeURIComponent(worldId)}`;
  return (
    <div className="world-panels" data-testid="world-hud">
      {tabs ? <LensTabs worldId={worldId} current="world" /> : <div className="lens-space" />}
      <section className="hud-card" aria-label="Live meter" data-testid="hud-meter">
        {events.length === 0 ? (
          <p>Nothing yet. This fills in once a run starts.</p>
        ) : (
          <>
            <span className="chip">{RUN_STATUS_LABEL[status]}</span>
            {status === "idle" ? (
              // No world.* event yet: words, not a "0" figure, beside a screen that may already
              // show a finished run (Bundle C3).
              <p className="hud-idle">The run has not started. No credits used yet.</p>
            ) : (
              <div className="hud-figures">
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
              </div>
            )}
            {saved && <AppLink to="/estimate">How we estimate</AppLink>}
          </>
        )}
      </section>
      <WorldPauseSlot worldId={worldId} />
      <div className="hud-count">
        <h2>Needs you</h2>
        {waiting > 0 && <AppLink to={withWorld("/needs-you", worldId)}>Open the queue</AppLink>}
        <span className={waiting > 0 ? "chip chip-needs" : "chip"} data-testid="needs-count">
          {waiting}
        </span>
      </div>
      <div className="hud-slot">
        {layout === null || names === null ? (
          // The same first child as the loaded slot (an h2), so its top does not move on arrival.
          <>
            <h2>Team</h2>
            <p>{layoutRemote.status === "error" ? layoutRemote.message : "The team is loading…"}</p>
          </>
        ) : (
          <>
            <h2>Team</h2>
            <ul className="rows">
              {layout.semantic.agents.map((a) => (
                <li key={a.id}>
                  <Pick id={a.id} selected={selected} toggle={toggle}>
                    <span className="row-name">{names.get(a.id)}</span>
                    <span className="row-state">
                      {state?.agents[a.id]?.spawned || acted.has(a.id)
                        ? "Joined"
                        : "Not joined yet"}
                    </span>
                  </Pick>
                </li>
              ))}
            </ul>
            {layout.semantic.levels.map((level) => (
              <section key={level.id}>
                <h2>
                  <AppLink to={`${base}/inspect/${level.id}`}>Level {level.name}</AppLink>
                </h2>
                <ul className="rows">
                  {level.districts.flatMap((d) =>
                    d.buildings.map((b) => (
                      <li key={b.id}>
                        <Pick id={b.id} selected={selected} toggle={toggle}>
                          <span className="row-name">
                            {b.name}
                            <small>{d.name}</small>
                          </span>
                          <span className="row-state">
                            {BUILDING_STATE[state?.buildings[b.id]?.status ?? "hidden"]}
                          </span>
                        </Pick>
                      </li>
                    )),
                  )}
                </ul>
              </section>
            ))}
            {layout.semantic.gates.length > 0 && (
              <section>
                <h2>Gates</h2>
                <ul className="rows">
                  {layout.semantic.gates.map((g) => (
                    <li key={g.id}>
                      <Pick id={g.id} selected={selected} toggle={toggle}>
                        <span className="row-name">
                          Gate {g.id}
                          <small>{rankName(g.guards)}</small>
                        </span>
                        <span className="row-state">Approval gate</span>
                      </Pick>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
