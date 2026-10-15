// STUDIO-3: the Story and Steps tabs of a real run's World page, from its recorded events alone (HR-1, HR-5). Steps
// are the plan's units (world.planned unit_count) in the order an event first named them, each with the words of its
// own events; a unit no event has named yet is a planned step with no words. Nothing is estimated or timed, and an
// event type outside the known families never reaches the Story (it belongs to the Trace).
import type { RunEvent } from "./useRunEvents";

export type StepState = "done" | "working" | "started" | "stopped" | "planned";

export interface RunStep {
  /** The unit id, or `planned-N` for a step no event has named yet. */
  readonly key: string;
  readonly state: StepState;
  /** The summary of the unit's first event; empty for a planned step. */
  readonly title: string;
  /** The summary of the unit's latest event when it differs from the first; empty otherwise. */
  readonly detail: string;
  /** Recorded time of day (UTC) of the unit's latest event; empty for a planned step. */
  readonly at: string;
}

export interface RunSteps {
  readonly steps: readonly RunStep[];
  /** world.planned unit_count; null until the plan is recorded. */
  readonly total: number | null;
  readonly done: number;
}

const UNIT_EVENT = /^(agent\.(assigned|working)|building\.(constructing|operational))$/;
const STORY_FAMILY =
  /^(world|plan|budget|level|district|building|agent|skill|artifact|approval|policy|data|connection|meeting|channel)\./;

const objectOf = (data: unknown): Record<string, unknown> =>
  data && typeof data === "object" ? (data as Record<string, unknown>) : {};
// The recorded time of day (UTC) straight from the ISO timestamp: no clock is read.
export const clockOf = (ts: string): string => /^\d{4}-\d\d-\d\dT(\d\d:\d\d)/.exec(ts)?.[1] ?? "";

export function runSteps(events: readonly RunEvent[]): RunSteps {
  const planned = [...events].reverse().find((e) => e.type === "world.planned");
  const count = objectOf(planned?.data).unit_count;
  const total = typeof count === "number" && count > 0 ? count : null;
  const order: string[] = [];
  const seen = new Map<string, RunEvent[]>();
  const buildingUnit = new Map<string, string>();
  const finished = new Set<string>();
  let completed = false;
  let stoppedAt: string | null = null;
  for (const e of events) {
    const unit = UNIT_EVENT.test(e.type) ? objectOf(e.data).unit : null;
    if (typeof unit === "string") {
      if (!seen.has(unit)) {
        seen.set(unit, []);
        order.push(unit);
      }
      seen.get(unit)?.push(e);
      if (e.type.startsWith("building.") && e.target) buildingUnit.set(e.target, unit);
    }
    if (e.type === "building.completed" && e.target) {
      const of = buildingUnit.get(e.target);
      if (of) {
        finished.add(of);
        seen.get(of)?.push(e);
      }
    }
    if (e.type === "world.completed") completed = true;
    if (e.type === "world.failed") {
      const u = objectOf(e.data).unit;
      stoppedAt = typeof u === "string" ? u : null;
    }
    if (e.type === "world.started" || e.type === "world.resumed") stoppedAt = null;
  }
  const said = (e: RunEvent | undefined): string => (e?.summary ?? "").trim();
  const steps: RunStep[] = order.map((unit) => {
    const mine = seen.get(unit) ?? [];
    const first = said(mine.find((e) => said(e) !== ""));
    const lastEvent = [...mine].reverse().find((e) => said(e) !== "");
    const last = said(lastEvent);
    const working = mine.some((e) => e.type !== "agent.assigned");
    const state: StepState =
      completed || finished.has(unit)
        ? "done"
        : stoppedAt === unit
          ? "stopped"
          : working
            ? "working"
            : "started";
    return {
      key: unit,
      state,
      title: first,
      detail: last !== first ? last : "",
      at: lastEvent ? clockOf(lastEvent.ts) : "",
    };
  });
  const missing = total === null ? 0 : Math.max(0, total - steps.length);
  for (let i = 0; i < missing; i++) {
    steps.push({
      key: `planned-${steps.length + 1}`,
      state: completed ? "done" : "planned",
      title: "",
      detail: "",
      at: "",
    });
  }
  return { steps, total, done: steps.filter((s) => s.state === "done").length };
}

/** The Story: every recorded event of a known family that says something, newest first. */
export function storyOf(events: readonly RunEvent[]): readonly RunEvent[] {
  return events
    .filter((e) => STORY_FAMILY.test(e.type) && (e.summary ?? "").trim() !== "")
    .slice()
    .reverse();
}
