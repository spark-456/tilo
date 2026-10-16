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
  /** True from agent.working until the agent's next event: the tool icon over it (WORLD-LIVE). */
  readonly working: boolean;
  /** The short note of the agent's latest agent.handoff and who got it, until its next event (WORLD-LIVE). */
  readonly say: { readonly text: string; readonly to: string } | null;
  /** Where the agent stood before a meeting room called it to the hall; it walks back on meeting.adjourned. */
  readonly back: string | null;
  /** TILO-T-WORLD: the building the agent works at: the one its latest agent.working named, else the first
   * building an agent.moved sent it to (a Lead's or the Director's post). Null until an event says so. */
  readonly post: string | null;
  /** TILO-T-WORLD: the seq of the agent's own agent.handoff while it is its latest event; it talks with the receiver
   * for TALK_WINDOW events, then stands at its post (`standingAt`). Null otherwise. */
  readonly doneAt: number | null;
}

/** How many later events a handing-over agent stays beside its receiver (the design's talkWin: 2). */
export const TALK_WINDOW = 2;

/** Where an agent stands, from the record alone (TILO-T-WORLD): a room's hall while it is in one, its post once its
 * handoff is older than the talk window, else the place its last event put it. */
export function standingAt(state: WorldState, agent: AgentState): string | null {
  if (agent.back !== null || agent.doneAt === null || agent.post === null) return agent.location;
  return state.seq - agent.doneAt > TALK_WINDOW ? agent.post : agent.location;
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

/** A layout gate as the recorded events leave it (the rules of needs-you/reduce.ts, CR-07): shut
 * until approval.requested, open once a person or Team Lead approves, "policy" once the policy
 * engine opened it (HR-7). Nothing says a gate is open until an event does. */
export type GateState = "closed" | "waiting" | "open" | "policy";

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
  readonly gates: Readonly<Record<string, GateState>>;
  /** The layout's Meeting Hall building, where a convened room gathers (WORLD-LIVE), or null. */
  readonly hall: string | null;
  /** Open meeting rooms: room id -> who sits in it, until meeting.adjourned (WORLD-LIVE). */
  readonly rooms: Readonly<Record<string, readonly string[]>>;
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
    agents[id] = {
      id,
      spawned: false,
      location: null,
      working: false,
      say: null,
      back: null,
      post: null,
      doneAt: null,
    };
  }
  const gates: Record<string, GateState> = {};
  for (const gate of layout.semantic.gates) gates[gate.id] = "closed";
  const hall =
    layout.semantic.levels
      .flatMap((l) => l.districts)
      .flatMap((d) => d.buildings)
      .find((b) => b.common_type === "meeting_hall")?.id ?? null;
  return {
    seq: 0,
    trace: [],
    status: "idle",
    levels,
    districts,
    buildings,
    agents,
    gates,
    hall,
    rooms: {},
  };
}

const BUILDING_STATUS_BY_VERB: Readonly<Record<string, BuildingStatus>> = {
  planned: "planned",
  constructing: "constructing",
  operational: "operational",
  completed: "completed",
  archived: "archived",
};

const NOTE_MAX = 140;

/** An agent.handoff's note: the envelope's own summary, else the event's line, cut to one short line. */
function noteOf(event: Event): { text: string; to: string } | null {
  const envelope = (event.data as Record<string, unknown> | null)?.envelope as
    | { summary?: unknown }
    | undefined;
  const own = typeof envelope?.summary === "string" ? envelope.summary : "";
  const raw = own.trim() ? own : event.summary;
  const text = raw.replace(/\s+/g, " ").trim().slice(0, NOTE_MAX);
  return text ? { text, to: event.target } : null;
}

function gateAfter(event: Event, verb: string): GateState | null {
  if (verb === "requested") return "waiting";
  const by = event.authz?.by;
  if (event.type === "policy.applied") return by === "policy" ? "policy" : null;
  if (verb !== "resolved" || (by !== "person" && by !== "team_lead")) return null;
  const option = (event.data as Record<string, unknown> | null)?.option;
  return option === "approve" ? "open" : option === "edit" || option === "hold" ? "closed" : null;
}

/** The agent's post after one of its own events: where it works (agent.working) wins; else its first building. */
function postAfter(
  agent: AgentState,
  verb: string,
  target: string | null,
  building: boolean,
): string | null {
  if (!building || target === null) return agent.post;
  return verb === "working" ? target : (agent.post ?? target);
}

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
        // WORLD-LIVE: whoever spawns an agent that already stands somewhere brings it out there.
        const at = state.agents[event.actor]?.location ?? null;
        return {
          ...state,
          agents: {
            ...state.agents,
            [spawnedId]: { ...agent, spawned: true, location: agent.location ?? at },
          },
        };
      }
      if (verb === "retired") {
        // The Lead retires a worker: the worker (the target) puts its tool and its note away.
        const gone = state.agents[event.target];
        if (!gone) return state;
        return {
          ...state,
          agents: { ...state.agents, [gone.id]: { ...gone, working: false, say: null } },
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
      // The actor's own next event ends its last note and tool (WORLD-LIVE: both exist only because an event said so).
      const next: AgentState = {
        ...agent,
        working: verb === "working",
        say: verb === "handoff" || verb === "assigned" ? noteOf(event) : null,
        location: isLocation ? event.target : agent.location,
        post: postAfter(
          agent,
          verb,
          isLocation ? event.target : null,
          event.target in state.buildings,
        ),
        doneAt: verb === "handoff" ? event.seq : null,
      };
      return { ...state, agents: { ...state.agents, [agent.id]: next } };
    }
    case "meeting": {
      // WORLD-LIVE: a person's room (meeting.convened .. meeting.adjourned). Its agents gather in the layout's Meeting
      // Hall and go back to where they stood when it closes; with no hall in the layout nobody moves (nothing guessed).
      const data = (event.data ?? {}) as { room_id?: unknown; lead?: unknown; agents?: unknown };
      const room = typeof data.room_id === "string" ? data.room_id : null;
      if (room === null) return state;
      if (verb === "convened") {
        if (state.hall === null || room in state.rooms) return state;
        const named = [data.lead, ...(Array.isArray(data.agents) ? data.agents : [])];
        const members = named.filter(
          (id): id is string => typeof id === "string" && id in state.agents,
        );
        const agents = { ...state.agents };
        for (const id of members) {
          const agent = agents[id] as AgentState;
          agents[id] = {
            ...agent,
            back: agent.back ?? standingAt(state, agent),
            location: state.hall,
            working: false,
            say: null,
          };
        }
        return { ...state, agents, rooms: { ...state.rooms, [room]: members } };
      }
      if (verb === "adjourned") {
        const members = state.rooms[room];
        if (!members) return state;
        const agents = { ...state.agents };
        for (const id of members) {
          const agent = agents[id] as AgentState;
          agents[id] = { ...agent, location: agent.back ?? agent.location, back: null, say: null };
        }
        const { [room]: _closed, ...rest } = state.rooms;
        return { ...state, agents, rooms: rest };
      }
      return state;
    }
    case "approval":
    case "policy": {
      const gateId = (event.data as Record<string, unknown> | null)?.gate_id;
      if (typeof gateId !== "string" || !(gateId in state.gates)) return state;
      const next = gateAfter(event, verb);
      return next ? { ...state, gates: { ...state.gates, [gateId]: next } } : state;
    }
    default:
      return state;
  }
}

export function applyEvent(state: WorldState, event: Event, _layout: Layout): WorldState {
  // A duplicate or out-of-order event (seq <= the highest applied) is ignored: seq never goes
  // down and each seq gets at most one Trace row.
  if (event.seq <= state.seq) return state;
  const withSeqAndTrace: WorldState = {
    ...state,
    seq: event.seq,
    trace: [...state.trace, { seq: event.seq, type: event.type }],
  };
  if (!isKnownType(event.type)) return withSeqAndTrace; // HR-5: trace only
  return applyKnown(withSeqAndTrace, event);
}

export function reduce(layout: Layout, events: readonly Event[]): WorldState {
  // Folds with an empty trace and collects the rows once: appending to a state copies its trace, so
  // a plain fold is O(n^2) in the run's length (FR-WLD-08: 4 s at 20,000 events).
  let state = createInitialState(layout);
  const trace: WorldState["trace"] = [];
  for (const event of events) {
    const next = applyEvent(state, event, layout);
    if (next === state) continue; // a duplicate or out-of-order event changes nothing
    trace.push(...next.trace);
    state = { ...next, trace: [] };
  }
  return { ...state, trace };
}
