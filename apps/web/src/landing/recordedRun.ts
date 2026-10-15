// STUDIO-6 (HR-1, HR-4): the landing page's central stage replays ONE recorded run that already ships with the app,
// the village-basic stream and its solver layout (contracts/fixtures, copied into src/api/fixtures and pinned there by
// fixtures.drift.test.ts). This module folds that record, event by event, into what the stage shows after each event.
// Nothing is invented: every word is an event's own summary, every building and helper exists because an event made
// it, and a frame changes only at an event. The stage labels all of it as a recorded example, never as live work.
import type { Event, Layout } from "@tilo/contracts";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { LAYOUT_VILLAGE_BASIC } from "../api/fixtures/layout";
import type { Plan, PlanAgent, PlanBuilding } from "../park/api/types";

export interface StoryLine {
  readonly seq: number;
  /** Who did it, in plain words: "You", "Tilo" or the agent's rank ("Director", "Specialist"). */
  readonly who: string;
  /** The agent's rank for its picture, or null for you and for Tilo itself. */
  readonly rank: string | null;
  readonly text: string;
  /** An approval the record asks for, an approval given, or anything else. */
  readonly tone: "gate" | "yes" | "info";
}

export interface StageFrame {
  /** How many events of the record this frame has folded in (0 = none yet). */
  readonly step: number;
  /** What the person asked for (the record's world.requested title), once asked. */
  readonly ask: string | null;
  /** The newest story lines, oldest first (at most three). */
  readonly lines: readonly StoryLine[];
  /** The city as recorded so far, or null before the first building is planned. */
  readonly plan: Plan | null;
  /** The record's world.completed summary, once the run is done. */
  readonly done: string | null;
}

export interface RecordedRun {
  readonly events: readonly Event[];
  /** frames[n] is the stage after the first n events; frames[0] is the empty stage. */
  readonly frames: readonly StageFrame[];
  /** Notable lines of the record for the page's sections (each null when the record has none). */
  readonly facts: {
    readonly ask: string | null;
    readonly planned: string | null;
    readonly budget: string | null;
    readonly work: readonly string[];
    readonly gate: string | null;
    readonly yes: string | null;
    readonly after: string | null;
    readonly done: string | null;
  };
}

/** The layout's common building types the Park art kit draws as a named building (park/engines/world.ts KIT). */
const KIT_OF: Readonly<Record<string, string>> = {
  town_hall: "townhall",
  your_desk: "desk",
  library: "library",
  browser_station: "browser",
  workshop: "workshop",
  meeting_hall: "meeting",
  connector_post: "connector",
  memory_vault: "vault",
  treasury: "treasury",
  watchtower: "watchtower",
  delivery_dock: "dock",
  clock_tower: "clock",
};
/** The other common types draw as a generated building with a sign; a kit building keeps its own icon if the art
 * has it. Anything unknown gets a plain sign. */
const SIGN_OF: Readonly<Record<string, string>> = {
  mail_room: "mail",
  agent_foundry: "cog",
  expert_office: "person",
};
const SIGNS = new Set([
  "search",
  "mail",
  "doc",
  "chart",
  "person",
  "people",
  "cog",
  "clock",
  "coin",
]);

/** What a building event makes of the building (the art kit's states). */
const BUILDING_STATE: Readonly<Record<string, string>> = {
  "building.planned": "planned",
  "building.constructing": "construction",
  "building.operational": "active",
  "building.completed": "complete",
};

type LayoutBuilding =
  Layout["semantic"]["levels"][number]["districts"][number]["buildings"][number];

function artOf(b: LayoutBuilding): PlanBuilding {
  const kit = b.common_type ? KIT_OF[b.common_type] : undefined;
  if (kit) return { id: b.id, kit };
  const own = b.kit?.icon && SIGNS.has(b.kit.icon) ? b.kit.icon : undefined;
  const sign = own ?? (b.common_type ? SIGN_OF[b.common_type] : undefined) ?? "doc";
  return { id: b.id, gen: { name: b.name, fp: [2, 1], i: sign } };
}

const capital = (word: string): string => word.charAt(0).toUpperCase() + word.slice(1);

/** Fold the record into one frame per event. Pure and deterministic: same record, same frames. */
export function foldRun(events: readonly Event[], layout: Layout): RecordedRun {
  const rankOf = new Map(layout.semantic.agents.map((a) => [a.id, a.rank]));
  const districts = layout.semantic.levels.flatMap((l) => l.districts);
  const buildingIds = new Set(districts.flatMap((d) => d.buildings.map((b) => b.id)));

  const opened = new Set<string>(); // districts the record has set up
  const state = new Map<string, string>(); // building id -> art state
  const at = new Map<string, string>(); // agent id -> the building it last worked on
  const spawned: string[] = [];
  let ask: string | null = null;
  let done: string | null = null;
  const story: StoryLine[] = [];
  let lastKey = "";
  let lastPlan: Plan | null = null;

  const who = (actor: string): { who: string; rank: string | null } => {
    if (actor.startsWith("u_")) return { who: "You", rank: null };
    const rank = rankOf.get(actor);
    return rank ? { who: capital(rank), rank } : { who: "Tilo", rank: null };
  };

  const planNow = (): Plan | null => {
    const shown = districts
      .filter((d) => opened.has(d.id))
      .map((d) => ({
        id: d.id,
        name: d.name,
        icon: d.icon,
        buildings: d.buildings
          .filter((b) => state.has(b.id))
          .map((b) => ({ ...artOf(b), state: state.get(b.id) as string })),
      }))
      .filter((d) => d.buildings.length > 0);
    if (shown.length === 0) return null;
    const agents: PlanAgent[] = spawned.flatMap((id) => {
      const where = at.get(id);
      return where ? [{ at: where, rank: rankOf.get(id) ?? "specialist", expr: "neutral" }] : [];
    });
    const plan: Plan = { districts: shown, agents };
    // the same city keeps the same object, so its picture is drawn once (park/shell/cityCache.ts)
    const key = JSON.stringify(plan);
    if (key !== lastKey) {
      lastKey = key;
      lastPlan = plan;
    }
    return lastPlan;
  };

  const frames: StageFrame[] = [{ step: 0, ask: null, lines: [], plan: null, done: null }];
  for (const [i, e] of events.entries()) {
    const target = e.target ?? "";
    if (e.type === "world.requested") {
      const title = (e.data as { title?: unknown } | null)?.title;
      ask = typeof title === "string" ? title : e.summary;
    }
    if (e.type === "district.created" && target) opened.add(target);
    const art = BUILDING_STATE[e.type];
    if (art && buildingIds.has(target)) {
      state.set(target, art);
      if (e.type !== "building.planned" && rankOf.has(e.actor)) at.set(e.actor, target);
    }
    if (e.type === "agent.spawned" && target && !spawned.includes(target)) spawned.push(target);
    if (e.type === "world.completed") done = e.summary;
    story.push({
      seq: e.seq,
      ...who(e.actor),
      text: e.summary,
      tone:
        e.type === "approval.requested"
          ? "gate"
          : e.type === "approval.resolved" || e.type === "budget.granted"
            ? "yes"
            : "info",
    });
    frames.push({ step: i + 1, ask, lines: story.slice(-3), plan: planNow(), done });
  }

  const first = (type: string): Event | undefined => events.find((e) => e.type === type);
  const after = (type: string, next: string): Event | undefined => {
    const from = events.findIndex((e) => e.type === type);
    return from < 0 ? undefined : events.slice(from + 1).find((e) => e.type === next);
  };
  return {
    events,
    frames,
    facts: {
      ask,
      planned: first("world.planned")?.summary ?? null,
      budget: first("budget.granted")?.summary ?? null,
      work: events
        .filter((e) => e.type === "artifact.created" || e.type === "artifact.reviewed")
        .map((e) => e.summary),
      gate: first("approval.requested")?.summary ?? null,
      yes: first("approval.resolved")?.summary ?? null,
      after: after("approval.resolved", "data.transfer")?.summary ?? null,
      done,
    },
  };
}

/** The one recorded run the landing page replays. */
export const RECORDED_RUN: RecordedRun = foldRun(EVENTS_VILLAGE_BASIC, LAYOUT_VILLAGE_BASIC);
