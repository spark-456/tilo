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
  | "archived"
  | "needs"
  | "failed";

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
  /** TW-6: agent raises hand on approval.requested, drops hand on approval.resolved */
  readonly hand: boolean;
}

/** How many later events a handing-over agent stays beside its receiver (the design's talkWin: 2). */
export const TALK_WINDOW = 2;

/** Where an agent stands, from the record alone (TILO-T-WORLD): a room's hall while it is in one, its post once its
 * handoff is older than the talk window, else the place its last event put it. */
export function standingAt(state: WorldState, agent: AgentState): string | null {
  if (state.status === "completed" && state.dock) return state.dock;
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
  /** The layout's Delivery Dock building, where deliverables arrive (TW-3) and agents gather on world.completed (TW-5), or null. */
  readonly dock: string | null;
  /** The layout's named destinations for a routed question. Null means the layout supplied no honest place. */
  readonly desk: string | null;
  readonly expertOffice: string | null;
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
      hand: false,
    };
  }
  const gates: Record<string, GateState> = {};
  for (const gate of layout.semantic.gates) gates[gate.id] = "closed";
  const allBuildings = layout.semantic.levels
    .flatMap((l) => l.districts)
    .flatMap((d) => d.buildings);
  const hall =
    // Only a hall the layout names as one: never guessed from an id or another building type.
    allBuildings.find((b) => b.common_type === "meeting_hall" || b.name === "Meeting Hall")?.id ??
    null;
  const dock =
    // Only a dock the layout names as one: never guessed from an id or another building type.
    allBuildings.find((b) => b.common_type === "delivery_dock" || b.name === "Delivery Dock")?.id ??
    null;
  const desk = allBuildings.find((b) => b.common_type === "your_desk")?.id ?? null;
  const expertOffice = allBuildings.find((b) => b.common_type === "expert_office")?.id ?? null;
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
    dock,
    desk,
    expertOffice,
    rooms: {},
  };
}

const BUILDING_STATUS_BY_VERB: Readonly<Record<string, BuildingStatus>> = {
  planned: "planned",
  constructing: "constructing",
  operational: "operational",
  completed: "completed",
  archived: "archived",
  needs: "needs",
  failed: "failed",
};

const NOTE_MAX = 140;
/** agent.* verbs whose event is the agent saying something (its bubble shows the real line): TILO-T-WORLD adds help. */
const SAYS: ReadonlySet<string> = new Set(["handoff", "assigned", "help_requested"]);

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
      if (verb === "completed") {
        if (state.dock) {
          const moved: Record<string, AgentState> = {};
          for (const [id, ag] of Object.entries(state.agents)) {
            moved[id] = ag.spawned
              ? { ...ag, location: state.dock, working: false, say: null }
              : ag;
          }
          return { ...state, status: "completed", agents: moved };
        }
        return { ...state, status: "completed" };
      }
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
      const buildings = { ...state.buildings };
      if (verb === "planned") {
        if (state.hall && state.hall in buildings) {
          buildings[state.hall] = { id: state.hall, status: "operational" };
        }
        if (state.dock && state.dock in buildings) {
          buildings[state.dock] = { id: state.dock, status: "operational" };
        }
      }
      if (verb === "failed" && event.target in state.buildings) {
        buildings[event.target] = { id: event.target, status: "failed" };
      }
      return { ...state, ...(status ? { status } : {}), buildings };
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
      const handoffTo =
        verb === "handoff" && state.agents[event.target]
          ? standingAt(state, state.agents[event.target] as AgentState)
          : null;
      const next: AgentState = {
        ...agent,
        working: verb === "working",
        say: SAYS.has(verb) ? noteOf(event) : null,
        location: isLocation ? event.target : (handoffTo ?? agent.location),
        post: postAfter(
          agent,
          verb,
          isLocation ? event.target : null,
          event.target in state.buildings,
        ),
        doneAt: verb === "handoff" ? event.seq : null,
      };
      const buildings =
        verb === "blocked" && event.target in state.buildings
          ? {
              ...state.buildings,
              [event.target]: { id: event.target, status: "failed" as const },
            }
          : state.buildings;
      return { ...state, buildings, agents: { ...state.agents, [agent.id]: next } };
    }
    case "question": {
      // TILO-T-WORLD: an agent routing a question to a person says it: its bubble is the event's own line, to "You".
      const asker = state.agents[event.actor];
      if (verb !== "routed" || !asker) return state;
      const say = noteOf(event);
      const domain = (event.data as Record<string, unknown> | null)?.domain;
      const destination =
        typeof domain === "string" ? state.expertOffice : domain === null ? state.desk : null;
      return {
        ...state,
        agents: {
          ...state.agents,
          [asker.id]: {
            ...asker,
            working: false,
            say,
            location: destination ?? asker.location,
            doneAt: null,
          },
        },
      };
    }
    case "meeting": {
      // WORLD-LIVE: a person's room (meeting.convened / meeting.called .. meeting.adjourned / meeting.ended).
      // Its agents gather in the layout's Meeting Hall and go back to where they stood when it closes;
      // with no hall in the layout nobody moves (nothing guessed).
      const data = (event.data ?? {}) as {
        room_id?: unknown;
        card_id?: unknown;
        lead?: unknown;
        agents?: unknown;
        attendees?: unknown;
      };
      const room =
        typeof data.room_id === "string"
          ? data.room_id
          : typeof data.card_id === "string"
            ? data.card_id
            : "meeting";
      if (verb === "convened" || verb === "called" || verb === "started") {
        if (state.hall === null || room in state.rooms) return state;
        const attendees = Array.isArray(data.attendees) ? data.attendees : [];
        const named = [data.lead, ...(Array.isArray(data.agents) ? data.agents : []), ...attendees];
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
      if (verb === "adjourned" || verb === "ended") {
        const members =
          state.rooms[room] ??
          (Object.keys(state.rooms).length === 1 ? Object.values(state.rooms)[0] : undefined);
        if (!members) return state;
        const agents = { ...state.agents };
        for (const id of members) {
          const agent = agents[id] as AgentState;
          if (agent) {
            agents[id] = {
              ...agent,
              location: agent.back ?? agent.location,
              back: null,
              say: null,
            };
          }
        }
        const { [room]: _closed, ...rest } = state.rooms;
        return { ...state, agents, rooms: rest };
      }
      return state;
    }
    case "artifact": {
      if (verb === "delivered" && state.dock && state.buildings[state.dock]) {
        return {
          ...state,
          buildings: {
            ...state.buildings,
            [state.dock]: { ...state.buildings[state.dock], status: "completed" },
          },
        };
      }
      return state;
    }
    case "approval":
    case "policy": {
      const buildings = { ...state.buildings };
      if (event.target in buildings) {
        if (verb === "requested") {
          buildings[event.target] = { ...buildings[event.target], status: "needs" };
        } else if (verb === "resolved") {
          buildings[event.target] = { ...buildings[event.target], status: "operational" };
        }
      }
      let nextState = buildings !== state.buildings ? { ...state, buildings } : state;
      const gateId = (event.data as Record<string, unknown> | null)?.gate_id;
      if (typeof gateId === "string" && gateId in nextState.gates) {
        const nextGate = gateAfter(event, verb);
        if (nextGate)
          nextState = { ...nextState, gates: { ...nextState.gates, [gateId]: nextGate } };
      }
      if (family === "approval") {
        if (verb === "requested" && event.actor) {
          const a = nextState.agents[event.actor];
          if (a) {
            nextState = {
              ...nextState,
              agents: { ...nextState.agents, [event.actor]: { ...a, hand: true } },
            };
          }
        } else if (verb === "resolved") {
          const updated = { ...nextState.agents };
          let changed = false;
          for (const [id, a] of Object.entries(updated)) {
            if (a.hand) {
              updated[id] = { ...a, hand: false };
              changed = true;
            }
          }
          if (changed) nextState = { ...nextState, agents: updated };
        }
      }
      return nextState;
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
