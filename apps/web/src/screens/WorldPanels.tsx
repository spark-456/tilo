// S-04 HUD panels (PRD 18.3): the meter, needs-you count, roster and a keyboard world outline for
// one world, in the right rail on desktop and a bottom sheet on mobile. Every number is derived
// from the recorded events (HR-1); before the first event nothing shows a figure (UX-3, HR-2).
import type { Layout } from "@tilo/contracts";
import { useClient } from "../api/ClientProvider";
import { reduce } from "../world/reducer";
import { creditsUsed, useRunLog, waitingForYou } from "../world/runLog";
import { AppLink } from "./AppLink";
import { LensTabs } from "./LensTabs";
import { useRemote } from "./remote";

const STATUS = {
  idle: "Getting ready",
  started: "Working",
  paused: "Paused",
  completed: "Done",
  failed: "Stopped with an error",
} as const;
const BUILDING = {
  hidden: "not planned yet",
  planned: "planned",
  constructing: "being built",
  operational: "at work",
  completed: "finished",
  archived: "archived",
} as const;

/** `tabs`: show the lens tabs (S-04 has no page header of its own; the lens screens do). */
export function WorldPanels({ worldId, tabs = true }: { worldId: string; tabs?: boolean }) {
  const client = useClient();
  const events = useRunLog(client, worldId);
  const [remote] = useRemote("load the world", () => client.getLayout(worldId));
  const layout: Layout | null = remote.status === "ready" ? remote.value : null;
  const state = layout ? reduce(layout, events) : null;
  const waiting = waitingForYou(events);
  const base = `/world/${encodeURIComponent(worldId)}`;
  return (
    <div className="world-panels" data-testid="world-hud">
      {tabs && <LensTabs worldId={worldId} current="world" />}
      <h2>Activity</h2>
      {events.length === 0 ? (
        <p className="hud-meter" data-testid="hud-meter">
          Nothing yet. This fills in once a run starts.
        </p>
      ) : (
        <p className="hud-meter" data-testid="hud-meter">
          <span className="hud-line">{state ? STATUS[state.status] : "Working"}</span>{" "}
          <span className="hud-line">Credits used so far: {creditsUsed(events)}</span>
        </p>
      )}
      <h2>Needs you</h2>
      <p>
        {waiting === 0 ? "Nothing needs you." : `${waiting} waiting. `}
        {waiting > 0 && <AppLink to="/needs-you">Open the queue</AppLink>}
      </p>
      <div className="hud-slot">
        {layout === null ? (
          <p>{remote.status === "error" ? remote.message : "The roster is loading…"}</p>
        ) : (
          <>
            <h2>Roster</h2>
            <ul className="outline">
              {layout.semantic.agents.map((a) => (
                <li key={a.id}>
                  <AppLink to={`${base}/inspect/${encodeURIComponent(a.id)}`}>
                    {a.rank} {a.id}
                  </AppLink>
                  {" · "}
                  {state?.agents[a.id]?.spawned ? "joined" : "not joined yet"}
                </li>
              ))}
            </ul>
            <h2>World outline</h2>
            <ul className="outline">
              {layout.semantic.levels.map((level) => (
                <li key={level.id}>
                  <AppLink to={`${base}/inspect/${level.id}`}>Level {level.name}</AppLink>
                  <ul>
                    {level.districts.flatMap((d) =>
                      d.buildings.map((b) => (
                        <li key={b.id}>
                          <AppLink to={`${base}/inspect/${b.id}`}>{b.name}</AppLink>
                          {" · "}
                          {d.name}, {BUILDING[state?.buildings[b.id]?.status ?? "hidden"]}
                        </li>
                      )),
                    )}
                  </ul>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
