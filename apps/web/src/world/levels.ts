// What the S-04 levels panel and the scrubber's marks say, derived from the recorded events and the
// reduced state alone (HR-1, HR-5): no figure exists that an event did not produce.
import type { Event, Layout } from "@tilo/contracts";
import type { WorldState } from "./reducer";
import { isKnownType } from "./registry";

export interface LevelRow {
  readonly id: string;
  /** 1 for the first level of the layout, as the badge reads (L1). */
  readonly number: number;
  readonly name: string;
  /** Buildings finished of the level's buildings, 0..100; a finished level is 100. */
  readonly percent: number;
  /** True when `percent` rests on a recorded event (a building or level event, or the run finished); a started
   * run with none has no honest number, so the screen shows none (HR-1). */
  readonly measured: boolean;
  /** The summary of the latest event of this level, or null before one. */
  readonly line: string | null;
  /** The level the latest levelled event belongs to: where the run is at the replay point. */
  readonly active: boolean;
}

/** How many buildings a layout plans, over all levels. */
export const buildingCount = (layout: Layout): number =>
  layout.semantic.levels.reduce(
    (n, level) => n + level.districts.reduce((m, d) => m + d.buildings.length, 0),
    0,
  );

/** A run that recorded world.completed but never a building, district or level event: its workstreams are not
 * tracked one by one, so the run finishing is the only record, and it finished all of them (HR-1). */
const finishedWithoutProgress = (state: WorldState, events: readonly Event[]): boolean =>
  state.status === "completed" && !events.some((e) => /^(building|district|level)\./.test(e.type));

/** The levels of a layout, top to bottom (the last level is the highest). */
export function levelRows(
  layout: Layout,
  state: WorldState,
  events: readonly Event[],
): readonly LevelRow[] {
  const runDone = finishedWithoutProgress(state, events);
  const lines = new Map<string, string>();
  let active: string | null = null;
  for (const e of events) {
    if (!isKnownType(e.type) || e.level === null || e.level === undefined) continue;
    active = e.level;
    if (e.summary) lines.set(e.level, e.summary);
  }
  return layout.semantic.levels
    .map((level, i): LevelRow => {
      const buildings = level.districts.flatMap((d) => d.buildings);
      const done = buildings.filter((b) => state.buildings[b.id]?.status === "completed").length;
      const levelDone = state.levels[level.id]?.completed === true;
      const percent =
        levelDone || runDone
          ? 100
          : buildings.length === 0
            ? 0
            : Math.round((done / buildings.length) * 100);
      return {
        id: level.id,
        number: i + 1,
        name: level.name,
        percent,
        measured:
          levelDone || runDone || buildings.some((b) => state.buildings[b.id]?.status !== "hidden"),
        line: lines.get(level.id) ?? null,
        active: level.id === active,
      };
    })
    .reverse();
}

/** A building's state for the side panel: its own events win; a run that recorded world.completed has finished
 * every workstream, and one that recorded world.planned has planned them (HR-1: the recorded run, not a default). */
export function buildingStatus(
  state: WorldState,
  id: string,
  events: readonly Event[],
): WorldState["buildings"][string]["status"] {
  const own = state.buildings[id]?.status ?? "hidden";
  if (own !== "hidden") return own;
  if (finishedWithoutProgress(state, events)) return "completed";
  return events.some((e) => e.type === "world.planned") ? "planned" : own;
}

export type MarkKind = "decision" | "done" | "problem";

export interface ScrubMark {
  /** The stop just after the event, as the scrubber counts them. */
  readonly index: number;
  readonly kind: MarkKind;
}

const MARK_KIND: Readonly<Record<string, MarkKind>> = {
  "approval.requested": "decision",
  "level.completed": "done",
  "world.completed": "done",
  "alert.raised": "problem",
  "world.failed": "problem",
};

/** The stops worth finding on the scrubber's track: a decision asked for, a level or the run
 * finished, a problem raised. Each is one registered event the run recorded. */
export function scrubMarks(events: readonly Event[]): readonly ScrubMark[] {
  const marks: ScrubMark[] = [];
  events.forEach((e, i) => {
    const kind = MARK_KIND[e.type];
    if (!kind || !isKnownType(e.type)) return;
    // A level finishing and the run finishing on the next event are one place on the track.
    const prev = marks[marks.length - 1];
    if (prev && prev.kind === kind && i + 1 - prev.index <= 1) marks.pop();
    marks.push({ index: i + 1, kind });
  });
  return marks;
}
