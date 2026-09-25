// FR-WLD-04: a pure reducer (layout, events) -> world state, no clock/randomness/I/O. HR-5: an
// unregistered type only ever touches `seq`/`trace` (frame.ts decides what actually renders).
import type { Event, Layout } from "@tilo/contracts";
import { isKnownType } from "./registry";

export type BuildingStatus =
  | "hidden"
  | "planned"
  | "constructing"
  | "operational"
  | "completed"
  | "archived";

export interface AgentState {
  readonly id: string;
  readonly spawned: boolean;
  /** Last building/district/level id the agent was placed at, or null. */
  readonly location: string | null;
}

export interface BuildingState {
  readonly id: string;
  readonly status: BuildingStatus;
}

export interface LevelState {
  readonly id: string;
  readonly completed: boolean;
}

export interface DistrictState {
  readonly id: string;
  readonly completed: boolean;
}

export type WorldStatus = "idle" | "started" | "paused" | "completed" | "failed";

export interface WorldState {
  readonly seq: number;
  // Mutable array type (not ReadonlyArray) so reducer.test.ts's own cast compiles; applyEvent
  // still never mutates an existing trace array in place (always spreads into a new one).
  readonly trace: Array<{ seq: number; type: string }>;
  readonly status: WorldStatus;
  readonly levels: Readonly<Record<string, LevelState>>;
  readonly districts: Readonly<Record<string, DistrictState>>;
  readonly buildings: Readonly<Record<string, BuildingState>>;
  readonly agents: Readonly<Record<string, AgentState>>;
}

function ids<T extends { id: string }>(items: readonly T[]): string[] {
  return items.map((i) => i.id);
}

export function createInitialState(layout: Layout): WorldState {
  const levels: Record<string, LevelState> = {};
  const districts: Record<string, DistrictState> = {};
  const buildings: Record<string, BuildingState> = {};
  for (const level of layout.semantic.levels) {
    levels[level.id] = { id: level.id, completed: false };
    for (const district of level.districts) {
      districts[district.id] = { id: district.id, completed: false };
      for (const building of district.buildings) {
        buildings[building.id] = { id: building.id, status: "hidden" };
      }
    }
  }
  const agents: Record<string, AgentState> = {};
  for (const id of ids(layout.semantic.agents)) {
    agents[id] = { id, spawned: false, location: null };
  }
  return { seq: 0, trace: [], status: "idle", levels, districts, buildings, agents };
}

const BUILDING_STATUS_BY_VERB: Readonly<Record<string, BuildingStatus>> = {
  planned: "planned",
  constructing: "constructing",
  operational: "operational",
  completed: "completed",
  archived: "archived",
};

/** Applies one known event's world effect. `state` is a fresh object already carrying the
 * bumped `seq` and `trace`; this only ever adds/replaces entries, never mutates nested maps. */
function applyKnown(state: WorldState, event: Event): WorldState {
  const [family, verb] = event.type.split(".");
  if (!family || !verb) return state;
  switch (family) {
    case "world": {
      const status: WorldStatus | undefined =
        verb === "started"
          ? "started"
          : verb === "paused"
            ? "paused"
            : verb === "resumed"
              ? "started"
              : verb === "completed"
                ? "completed"
                : verb === "failed"
                  ? "failed"
                  : undefined;
      return status ? { ...state, status } : state;
    }
    case "level": {
      const level = state.levels[event.target];
      if (!level) return state;
      return {
        ...state,
        levels: { ...state.levels, [level.id]: { ...level, completed: verb === "completed" } },
      };
    }
    case "district": {
      const district = state.districts[event.target];
      if (!district) return state;
      return {
        ...state,
        districts: {
          ...state.districts,
          [district.id]: { ...district, completed: verb === "completed" },
        },
      };
    }
    case "building": {
      const building = state.buildings[event.target];
      const status = BUILDING_STATUS_BY_VERB[verb];
      if (!building || !status) return state;
      return {
        ...state,
        buildings: { ...state.buildings, [building.id]: { ...building, status } },
      };
    }
    case "agent": {
      if (verb === "spawned") {
        const spawnedId = event.target;
        const agent = state.agents[spawnedId];
        if (!agent) return state;
        return {
          ...state,
          agents: { ...state.agents, [spawnedId]: { ...agent, spawned: true } },
        };
      }
      // Any other agent.* event: if `actor` is a known agent and `target` resolves to a
      // location (building/district/level id) this event moves that agent there (agent.moved,
      // agent.working, …) — structural, not keyed to any particular event type or scenario.
      const agent = state.agents[event.actor];
      if (!agent) return state;
      const isLocation =
        event.target in state.buildings ||
        event.target in state.districts ||
        event.target in state.levels;
      if (!isLocation) return state;
      return {
        ...state,
        agents: { ...state.agents, [agent.id]: { ...agent, location: event.target } },
      };
    }
    default:
      return state;
  }
}

export function applyEvent(state: WorldState, event: Event, _layout: Layout): WorldState {
  const withSeqAndTrace: WorldState = {
    ...state,
    seq: event.seq,
    trace: [...state.trace, { seq: event.seq, type: event.type }],
  };
  if (!isKnownType(event.type)) return withSeqAndTrace; // HR-5: trace only
  return applyKnown(withSeqAndTrace, event);
}

export function reduce(layout: Layout, events: readonly Event[]): WorldState {
  let state = createInitialState(layout);
  for (const event of events) state = applyEvent(state, event, layout);
  return state;
}
