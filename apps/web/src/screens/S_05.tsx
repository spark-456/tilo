// S-05 Inspect panel (PRD 18.3): one thing in the world (building, district, level or agent), what
// it is, where it sits, its state and every recorded event that names it. State comes from the
// reducer over the recorded events, never from a guess (HR-1, HR-5). Layout after the Inspect panel
// in design/source "Tilo World Player.dc.html".
import type { Event, Layout } from "@tilo/contracts";
import { useClient } from "../api/ClientProvider";
import { type WorldState, reduce } from "../world/reducer";
import { elapsed, useRunLog } from "../world/runLog";
import { AppLink } from "./AppLink";
import { Loaded } from "./FlowShell";
import { Placeholder } from "./Placeholder";
import { useRemote } from "./remote";
import type { ScreenProps } from "./routes";

interface Found {
  readonly kind: string;
  readonly name: string;
  readonly where: string;
  readonly state: (s: WorldState) => string;
}

const BUILDING_STATE = {
  hidden: "Not planned yet",
  planned: "Planned",
  constructing: "Being built",
  operational: "At work",
  completed: "Finished",
  archived: "Archived",
} as const;

/** The item with this id anywhere in the layout, with its place and its state text. */
export function findItem(layout: Layout, id: string): Found | null {
  for (const level of layout.semantic.levels) {
    if (level.id === id) {
      return {
        kind: "Level",
        name: level.name,
        where: "Top of the world",
        state: (s) => (s.levels[id]?.completed ? "Finished" : "In progress"),
      };
    }
    for (const district of level.districts) {
      if (district.id === id) {
        return {
          kind: "District",
          name: district.name,
          where: `Level ${level.name}, led by ${district.lead}`,
          state: (s) => (s.districts[id]?.completed ? "Finished" : "In progress"),
        };
      }
      for (const b of district.buildings) {
        if (b.id === id) {
          return {
            kind: b.kind === "common" ? "Common building" : "Building",
            name: b.name,
            where: `District ${district.name}, level ${level.name}`,
            state: (s) => BUILDING_STATE[s.buildings[id]?.status ?? "hidden"],
          };
        }
      }
    }
  }
  const agent = layout.semantic.agents.find((a) => a.id === id);
  if (!agent) return null;
  return {
    kind: "Agent",
    name: `${agent.rank} ${agent.id}`,
    where: agent.team_lead ? `Team of ${agent.team_lead}` : "Part of the team",
    state: (s) => (s.agents[id]?.spawned ? "Joined the team" : "Not joined yet"),
  };
}

const names = (e: Event, id: string): boolean => e.target === id || e.actor === id;

export function S_05({ params }: ScreenProps) {
  const [worldId = "", itemId = ""] = params;
  const client = useClient();
  const events = useRunLog(client, worldId);
  const [layout, retry] = useRemote("load the world", () => client.getLayout(worldId));
  return (
    <div className="screen-body wide" data-testid="inspect-panel">
      <p>
        <AppLink to={`/world/${encodeURIComponent(worldId)}`}>Back to the world</AppLink>
      </p>
      <Loaded what="the world" remote={layout} retry={retry} isEmpty={() => false}>
        {(l) => {
          const item = findItem(l, itemId);
          if (!item) {
            return (
              <>
                <h1>Not found</h1>
                <p>There is nothing called {itemId} in this world.</p>
              </>
            );
          }
          const mine = events.filter((e) => names(e, itemId));
          return (
            <>
              <h1>{item.name}</h1>
              <p className="screen-tag">
                {item.kind} · {item.where}
              </p>
              <p>
                <b>State:</b> {item.state(reduce(l, events))}
              </p>
              <Placeholder label="Follow in the world" />
              <h2>What happened here</h2>
              {mine.length === 0 ? (
                <p>No event has named this yet.</p>
              ) : (
                <ol className="story-list">
                  {mine.map((e) => (
                    <li key={e.seq}>
                      <span className="story-time">{elapsed(events, e)}</span>
                      <span>{e.summary}</span>
                    </li>
                  ))}
                </ol>
              )}
            </>
          );
        }}
      </Loaded>
    </div>
  );
}
