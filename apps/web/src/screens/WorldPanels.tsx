// S-04 HUD panels (PRD 18.3), after the "Live meter", needs-you and roster blocks of design/source
// "Tilo 2 Balanced Refined.dc.html" 2-1: hero figures, a needs-you count chip, roster and outline
// rows. Right rail on desktop, bottom sheet on mobile. Every figure is derived from the recorded
// events (HR-1); before the first event nothing shows a figure (UX-3, HR-2).
import type { Layout } from "@tilo/contracts";
import type { ReactNode } from "react";
import { useClient } from "../api/ClientProvider";
import { reduce } from "../world/reducer";
import { creditsUsed, useRunLog, waitingForYou } from "../world/runLog";
import {
  BUILDING_STATE,
  RUN_STATUS_LABEL,
  agentNames,
  budgetCap,
  worldStatus,
} from "../world/runSummary";
import { useSelection } from "../world/selection";
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

/** `tabs`: show the lens tabs (S-04 has no page header of its own; the lens screens do). Without
 * them the same height stays reserved, so the rail does not jump between world screens. */
export function WorldPanels({ worldId, tabs = true }: { worldId: string; tabs?: boolean }) {
  const client = useClient();
  const events = useRunLog(client, worldId);
  const [selected, , toggle] = useSelection(worldId);
  const [layoutRemote] = useRemote("load the world", () => client.getLayout(worldId));
  const [deliveryRemote] = useRemote("load the delivery", () => client.getDelivery(worldId));
  const layout: Layout | null = layoutRemote.status === "ready" ? layoutRemote.value : null;
  const state = layout ? reduce(layout, events) : null;
  const names = layout ? agentNames(layout) : null;
  const acted = new Set(events.map((e) => e.actor));
  const status = worldStatus(events);
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
            <div className="hud-figures">
              <div>
                <b>{creditsUsed(events)}</b>
                <span>{cap === null ? "credits used" : `credits of ${cap} approved`}</span>
              </div>
              <div>
                <b>{saved ? `${saved.low_min} to ${saved.high_min} min` : "Not yet"}</b>
                <span>saved · estimate</span>
              </div>
            </div>
            {saved && <AppLink to="/estimate">How we estimate</AppLink>}
          </>
        )}
      </section>
      <WorldPauseSlot worldId={worldId} />
      <div className="hud-count">
        <h2>Needs you</h2>
        {waiting > 0 && <AppLink to="/needs-you">Open the queue</AppLink>}
        <span className={waiting > 0 ? "chip chip-needs" : "chip"} data-testid="needs-count">
          {waiting}
        </span>
      </div>
      <div className="hud-slot">
        {layout === null || names === null ? (
          <p>{layoutRemote.status === "error" ? layoutRemote.message : "The team is loading…"}</p>
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
          </>
        )}
      </div>
    </div>
  );
}
