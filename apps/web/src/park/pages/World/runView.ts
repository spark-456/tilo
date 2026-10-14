// WORLD-USEFUL: what the person reads at a glance on a real run's World page, from the recorded events alone
// (HR-1, HR-5): one plain progress line, the plan's step count, what was assumed instead of asked, the recorded
// reason a run stopped, and whether a result can be read. Nothing here is estimated or timed; an event type the
// registry does not know changes nothing.
import type { RunEvent } from "./useRunEvents";

export type RunPhase =
  | "none"
  | "planning"
  | "ready"
  | "working"
  | "waiting"
  | "paused"
  | "done"
  | "failed";

export interface RunView {
  readonly phase: RunPhase;
  /** One plain sentence: where the run is and what the agents are doing now (only recorded words). */
  readonly line: string;
  /** Steps of the plan (world.planned unit_count), null until the plan is recorded. */
  readonly total: number | null;
  /** Distinct plan units an agent has been given or has worked on so far. */
  readonly begun: number;
  /** 0..100 from the recorded steps; null when no plan count is recorded. */
  readonly percent: number | null;
  /** The recorded reason the run stopped (world.failed data.reason); null unless it did. */
  readonly failure: { readonly reason: string; readonly unit: string | null } | null;
  /** What the run assumed instead of asking: events worded "Assumed: ..." (FR-INT-04), once each, in order. */
  readonly assumptions: readonly string[];
  /** True once world.completed and an artifact.delivered are both recorded: the result can be read. */
  readonly deliverable: boolean;
}

const ASSUMED = /^\s*assumed\s*:\s*(.+)$/is;
const UNIT_EVENT = /^(agent\.(assigned|working)|building\.(constructing|operational))$/;
const ACTIVITY = /^(agent|building|skill|data|artifact|approval|connection|meeting)\./;

const objectOf = (data: unknown): Record<string, unknown> =>
  data && typeof data === "object" ? (data as Record<string, unknown>) : {};
const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;
const sentence = (text: string): string => {
  const t = text.trim();
  return /[.!?]$/.test(t) ? t : `${t}.`;
};

export function runView(events: readonly RunEvent[]): RunView {
  const reversed = [...events].reverse();
  const last = (type: string): RunEvent | undefined => reversed.find((e) => e.type === type);
  const planned = last("world.planned");
  const count = objectOf(planned?.data).unit_count;
  const total = typeof count === "number" && count > 0 ? count : null;
  const units = new Set<string>();
  for (const e of events) {
    const unit = UNIT_EVENT.test(e.type) ? objectOf(e.data).unit : null;
    if (typeof unit === "string") units.add(unit);
  }
  const begun = total === null ? units.size : Math.min(units.size, total);
  const percent = total === null ? null : Math.round((begun / total) * 100);
  const worldEvent = reversed.find((e) => e.type.startsWith("world."));
  const open = Math.max(
    0,
    events.filter((e) => e.type === "approval.requested").length -
      events.filter((e) => e.type === "approval.resolved").length,
  );
  const assumptions: string[] = [];
  for (const e of events) {
    const said = ASSUMED.exec(e.summary ?? "")?.[1]?.trim();
    if (said && !assumptions.includes(said)) assumptions.push(said);
  }
  const doing = reversed.find(
    (e) => ACTIVITY.test(e.type) && (e.summary ?? "").trim() !== "",
  )?.summary;
  const step = begun > 0 && total !== null ? `Step ${begun} of ${total}` : "";
  const base = { total, begun, assumptions, failure: null, deliverable: false } as const;

  if (events.length === 0) {
    return {
      ...base,
      phase: "none",
      percent: null,
      line: "Getting ready. Nothing has been recorded yet.",
    };
  }
  if (worldEvent?.type === "world.failed") {
    const data = objectOf(worldEvent.data);
    const said = typeof data.reason === "string" ? data.reason.trim() : "";
    const reason = said !== "" ? said : worldEvent.summary;
    const unit = typeof data.unit === "string" ? data.unit : null;
    return {
      ...base,
      phase: "failed",
      percent,
      failure: { reason, unit },
      line: `${step ? `Stopped at ${step.toLowerCase()}` : "Stopped"}: ${sentence(reason)}`,
    };
  }
  if (worldEvent?.type === "world.completed") {
    const made = events.filter((e) => e.type === "artifact.delivered").length;
    const all = total === null ? "" : `. All ${plural(total, "step", "steps")} finished`;
    const out =
      made > 0
        ? `, ${plural(made, "deliverable", "deliverables")} ready below`
        : ", nothing was delivered";
    return {
      ...base,
      phase: "done",
      percent: 100,
      deliverable: made > 0,
      line: `Done${all}${out}.`,
    };
  }
  if (worldEvent?.type === "world.paused") {
    return {
      ...base,
      phase: "paused",
      percent,
      line: `Paused${step ? ` at ${step.toLowerCase()}` : ""}.`,
    };
  }
  if (!events.some((e) => e.type === "world.started")) {
    if (planned) {
      const steps = total === null ? "" : `: ${plural(total, "step", "steps")}`;
      return {
        ...base,
        phase: "ready",
        percent: 0,
        line: `The plan is ready${steps}. Waiting to start.`,
      };
    }
    const asked = last("plan.questions_asked");
    if (asked) {
      const n = Number(objectOf(asked.data).question_count) || 1;
      return {
        ...base,
        phase: "planning",
        percent: null,
        line: `The Director is waiting for your answers (${plural(n, "question", "questions")}).`,
      };
    }
    return {
      ...base,
      phase: "planning",
      percent: null,
      line: doing ? `Planning: ${sentence(doing)}` : "Planning.",
    };
  }
  if (open > 0) {
    const goes = step ? ` ${step} continues once you answer.` : "";
    return {
      ...base,
      phase: "waiting",
      percent,
      line: `Waiting for you: ${plural(open, "decision", "decisions")}.${goes}`,
    };
  }
  const head = step || "Working";
  return {
    ...base,
    phase: "working",
    percent,
    line: doing ? `${head}: ${sentence(doing)}` : `${head}.`,
  };
}
