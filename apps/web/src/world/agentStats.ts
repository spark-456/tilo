// TILO-T-WORLD: what the stats card and the agent panel say about one agent, from the recorded events alone (HR-1):
// who it is, where it stands, its task, the units it handed over, the tools it called, the credits its events
// carry and the last things it said. Nothing is estimated and nothing is filled in; an agent with no events has zeros.
import type { Event, Layout } from "@tilo/contracts";
import { type Message, messageOf } from "./conversations";
import { districtLabel } from "./labels";
import {
  TALK_WINDOW,
  type WorldState,
  applyEvent,
  createInitialState,
  standingAt,
} from "./reducer";
import { isKnownType } from "./registry";
import { agentNames, rankName } from "./runSummary";

export type AgentStatus =
  | "waiting"
  | "ready"
  | "working"
  | "handing over"
  | "finished"
  | "in a meeting";

export interface AgentStats {
  readonly id: string;
  readonly name: string;
  readonly role: string;
  readonly rank: string;
  /** The district the agent leads or its events were recorded in, by name. */
  readonly district: string | null;
  /** The building, district or level it stands at now, from the record; or null before any event placed it. */
  readonly at: { readonly id: string; readonly name: string } | null;
  /** What its Lead gave it (the latest agent.assigned to it), or null. */
  readonly task: string | null;
  readonly unitsDone: number;
  readonly tools: readonly string[];
  /** agent.working events it recorded (one per tool call or work step). */
  readonly workCalls: number;
  readonly credits: number;
  /** The last three messages it sent, oldest first. */
  readonly said: readonly Message[];
  readonly status: AgentStatus;
}

interface Acc {
  task: string | null;
  unitsDone: number;
  tools: string[];
  workCalls: number;
  credits: number;
  said: Message[];
  district: string | null;
}

/** "The Lead gave it: Triage the inbox" -> "Triage the inbox"; any other wording is kept whole. */
const taskOf = (summary: string): string => summary.replace(/^The Lead gave it:\s*/i, "").trim();

const round = (n: number): number => Math.round(n * 100) / 100;

export function agentStatsOf(layout: Layout, events: readonly Event[]): Map<string, AgentStats> {
  const names = agentNames(layout);
  const labels = new Map<string, string>();
  const ledBy = new Map<string, string>();
  for (const level of layout.semantic.levels) {
    labels.set(level.id, level.name);
    for (const district of level.districts) {
      labels.set(district.id, districtLabel(district));
      ledBy.set(district.lead, district.id);
      for (const building of district.buildings) labels.set(building.id, building.name);
    }
  }
  const acc = new Map<string, Acc>();
  for (const a of layout.semantic.agents) {
    acc.set(a.id, {
      task: null,
      unitsDone: 0,
      tools: [],
      workCalls: 0,
      credits: 0,
      said: [],
      district: ledBy.get(a.id) ?? null,
    });
  }
  let state: WorldState = createInitialState(layout);
  for (const event of events) {
    const next = applyEvent(state, event, layout);
    if (next === state) continue;
    state = next;
    const mine = acc.get(event.actor);
    if (mine) {
      mine.credits += event.credits;
      if (event.district && !mine.district) mine.district = event.district;
    }
    if (!isKnownType(event.type)) continue;
    const mineTarget = acc.get(event.target);
    if (event.type === "agent.assigned" && mineTarget) mineTarget.task = taskOf(event.summary);
    if (!mine) continue;
    if (event.type === "agent.handoff") mine.unitsDone += 1;
    if (event.type === "agent.working") {
      mine.workCalls += 1;
      const tool = (event.trace as { tool?: unknown } | null)?.tool;
      if (typeof tool === "string" && tool && !mine.tools.includes(tool)) mine.tools.push(tool);
    }
    const message = messageOf(event, state);
    if (message?.text) mine.said = [...mine.said.slice(-2), message];
  }
  const out = new Map<string, AgentStats>();
  for (const a of layout.semantic.agents) {
    const mine = acc.get(a.id) as Acc;
    const agent = state.agents[a.id];
    const stands = agent ? standingAt(state, agent) : null;
    const status: AgentStatus = !agent?.spawned
      ? "waiting"
      : agent.back !== null
        ? "in a meeting"
        : agent.working
          ? "working"
          : agent.doneAt !== null
            ? state.seq - agent.doneAt > TALK_WINDOW
              ? "finished"
              : "handing over"
            : "ready";
    out.set(a.id, {
      id: a.id,
      name: names.get(a.id) ?? a.id,
      role: rankName(a.rank),
      rank: a.rank,
      district: mine.district ? (labels.get(mine.district) ?? mine.district) : null,
      at: stands ? { id: stands, name: labels.get(stands) ?? stands } : null,
      task: mine.task,
      unitsDone: mine.unitsDone,
      tools: mine.tools,
      workCalls: mine.workCalls,
      credits: round(mine.credits),
      said: mine.said,
      status,
    });
  }
  return out;
}
