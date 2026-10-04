// What the Inspect panel and the selection bar say about one object (FR-WLD-06, PRD 18.3): its kind,
// name, place and state text, found in the layout (agents, levels, districts, buildings, islands)
// or in the events that carry it (artifacts). State comes from the reducer, never a guess (HR-1).
import type { Event, Layout } from "@tilo/contracts";
import type { WorldState } from "../world/reducer";
import { BUILDING_STATE, agentNames } from "../world/runSummary";

export interface Found {
  readonly kind: string;
  readonly name: string;
  readonly where: string;
  readonly state: (s: WorldState) => string;
}

const ARTIFACT_STATE: Readonly<Record<string, string>> = {
  "artifact.created": "Made",
  "artifact.reviewed": "Checked",
  "artifact.delivered": "Delivered",
  "artifact.versioned": "New version saved",
  "artifact.rolled_back": "Restored to an earlier version",
};
const ISLAND_STATE = {
  locked: "Locked",
  requested: "Waiting for consent",
  connected: "Connected",
  failed: "Connection lost",
} as const;

/** The item with this id anywhere in the layout or the events (artifacts), with its place and its
 * state text. */
export function findItem(layout: Layout, id: string, events: readonly Event[] = []): Found | null {
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
  const island = layout.semantic.islands.find((i) => i.id === id);
  if (island) {
    return {
      kind: "Island",
      name: island.name,
      where: `An outside system, reached by a ${island.bridge}`,
      state: () => ISLAND_STATE[island.state],
    };
  }
  const agent = layout.semantic.agents.find((a) => a.id === id);
  if (!agent) return artifact(events, id);
  return {
    kind: "Agent",
    name: agentNames(layout).get(id) ?? agent.id,
    where: agent.team_lead ? `Team of ${agent.team_lead}` : "Part of the team",
    state: (s) => (s.agents[id]?.spawned ? "Joined the team" : "Not joined yet"),
  };
}

/** An artifact exists once an event carries it (its item); its state is the latest artifact event. */
function artifact(events: readonly Event[], id: string): Found | null {
  const item = events.find((e) => e.item?.artifact_id === id)?.item;
  if (!item) return null;
  const latest = events.filter((e) => e.target === id && e.type in ARTIFACT_STATE).at(-1)?.type;
  return {
    kind: "Artifact",
    name: item.label,
    where: `A ${item.kind} in the world`,
    state: () => ARTIFACT_STATE[latest ?? ""] ?? "In use",
  };
}
