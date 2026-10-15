// SIMPLE-RUN-1: the one-step start. Park Home takes the task, makes the intake call, skips every Director question
// (the brief records each skip as "Assumed: ...", FR-INT-04), asks for the approaches and shows ONE confirm card
// with the recommended approach. The person's click on Start is the budget approval (the same `approve` call the
// old S-03 made), and the run's own world opens. Nothing here is a model call; every step is a tilo-api route.
import type { PlanApproach } from "@tilo/contracts";
import type { IntakeResult } from "../../api/client";
import type { HttpClient } from "../../api/http";
import { TiloApiError } from "../../api/http";
import type { Cadence } from "../../api/schedules";

// The weekly repeat's types and weekday names travel with the one-step start, so a page imports them from park/api.
export { WEEKDAYS } from "../../api/schedules";
export type { Cadence };
import type { Api } from "./index";

/** `caps.run_credits` in config/metering.yaml (services/api answers 422 above it): the most one approval may grant. */
export const MAX_RUN_CREDITS = 300;

/** `min_run_grant_credits` in config/run_grant.yaml (BQ-BUDGET-FLOOR-1): a Start always grants at least this many. The
 *  approaches reply's own `min_grant` wins when it is there, so a changed config never needs a web deploy. */
export const MIN_RUN_GRANT_CREDITS = 60;

export interface RunLine {
  /** The brief field the person's answer to the skipped question goes to, or null when it cannot be edited. */
  readonly field: string | null;
  readonly text: string;
}

/** What the confirm card shows, all of it from the server's replies. */
export interface RunPlan {
  readonly taskId: string;
  readonly goal: string;
  readonly lines: readonly RunLine[];
  readonly approachId: string;
  readonly approachLabel: string;
  readonly credits: { readonly min: number; readonly max: number };
  /** The grant Start approves: the approach's own maximum, within the API's ceiling. */
  readonly cap: number;
  readonly usd: number | null;
  readonly time: string;
}

export interface OneStepApi {
  /** Intake, skip every question, fetch the approaches. Throws a `TiloApiError` whose message is the reason. */
  prepare(text: string, files: readonly File[]): Promise<RunPlan>;
  /** The person changed one assumption: answer that question, then price the new brief again. */
  revise(taskId: string, field: string, answer: string): Promise<RunPlan>;
  /**
   * Approve the plan's cap and, when `repeat` is given, post one weekly schedule after the grant (FR-AGT-14). The run
   * has started whatever the schedule's answer: a refused repeat is `repeatRefused`, never an undone run.
   */
  start(plan: RunPlan, repeat?: Cadence | null): Promise<RunStart>;
}

export interface RunStart {
  readonly worldId: string;
  /** The plain reason the repeat was not set, or null (none asked, or it was set). */
  readonly repeatRefused: string | null;
}

/** The API takes a schedule title without control characters. */
const plainTitle = (text: string): string =>
  [...text]
    .map((ch) => ((ch.codePointAt(0) ?? 0) < 32 || /^[\u007f-\u009f]$/.test(ch) ? " " : ch))
    .join("")
    .slice(0, 140);

// Travels with the Api through its session wrappers like the quiz reader (quizApps.ts); the pinned `Api` keys stay.
const starters = new WeakMap<Api, () => OneStepApi | null>();
export const installOneStep = (api: Api, one: () => OneStepApi | null): void => {
  starters.set(api, one);
};
export function carryOneStep(from: Api, to: Api, enabled: () => boolean = () => true): Api {
  const one = starters.get(from);
  if (one) installOneStep(to, () => (enabled() ? one() : null));
  return to;
}
export const oneStepOf = (api: Api): OneStepApi | null => starters.get(api)?.() ?? null;

const BAD_REPLY = "Tilo sent a reply this page could not read.";
const NO_APPROACH = "Tilo found no way to do this task, so nothing was started. Try rewording it.";
const GENERIC = "Tilo could not accept that.";

/** The reason a person reads: the server's own words, or a sentence that names the step and the status. */
const said = (step: string, e: unknown): TiloApiError => {
  if (!(e instanceof TiloApiError)) return new TiloApiError(BAD_REPLY, 200, true, true);
  if (e.message !== GENERIC) return e;
  return new TiloApiError(
    `Tilo refused to ${step} (error ${e.status ?? "unknown"}). Nothing was started; try again.`,
    e.status,
    e.retryable,
    e.write,
    e.code,
  );
};

const isText = (v: unknown): v is string => typeof v === "string";

function planOf(
  taskId: string,
  brief: { goal?: unknown; assumptions?: unknown },
  asked: readonly { field: string; text: string }[],
  priced: {
    approaches: PlanApproach[];
    recommended: string;
    credit_usd: number;
    min_grant?: number;
  },
): RunPlan {
  const chosen =
    priced.approaches.find((a) => a.id === priced.recommended) ?? priced.approaches[0] ?? null;
  if (chosen === null) throw new TiloApiError(NO_APPROACH, 200, false, false);
  const fieldOf = new Map(asked.map((q) => [q.text, q.field]));
  const lines: RunLine[] = [];
  for (const a of Array.isArray(brief.assumptions) ? brief.assumptions : []) {
    const item = a as { question?: unknown; assumed?: unknown };
    if (!isText(item.assumed) || item.assumed.trim() === "") continue;
    const question = isText(item.question) ? item.question : null;
    lines.push({
      field: question === null ? null : (fieldOf.get(question) ?? null),
      text: item.assumed.trim(),
    });
  }
  // BQ-BUDGET-FLOOR-1: the card shows what Start grants, never less than the floor (the API raises a smaller cap to it).
  const floor = Math.min(
    typeof priced.min_grant === "number" &&
      Number.isFinite(priced.min_grant) &&
      priced.min_grant >= 0
      ? priced.min_grant
      : MIN_RUN_GRANT_CREDITS,
    MAX_RUN_CREDITS,
  );
  const top = Math.max(chosen.credits.max, floor);
  const max = Math.max(1, Math.ceil(top));
  const usd = Number.isFinite(priced.credit_usd)
    ? Math.min(max, MAX_RUN_CREDITS) * priced.credit_usd
    : null;
  const t = chosen.time;
  return {
    taskId,
    goal: isText(brief.goal) && brief.goal.trim() !== "" ? brief.goal.trim() : "Your task",
    lines,
    approachId: chosen.id,
    approachLabel: chosen.label,
    credits: { min: Math.min(chosen.credits.min, top), max: top },
    cap: Math.min(max, MAX_RUN_CREDITS),
    usd,
    time:
      t.min_s >= 60 && t.min_s % 60 === 0 && t.max_s % 60 === 0
        ? `${t.min_s / 60}–${t.max_s / 60} min`
        : `${t.min_s}–${t.max_s} s`,
  };
}

/** The one-step start over the app's HTTP client (the same routes the old S-02 and S-03 called). */
export function oneStepOver(http: HttpClient): OneStepApi {
  const asked = new Map<string, { field: string; text: string }[]>();
  const price = async (taskId: string, brief: { goal?: unknown; assumptions?: unknown }) => {
    let priced: Awaited<ReturnType<HttpClient["getApproaches"]>>;
    try {
      priced = await http.getApproaches(taskId);
    } catch (e) {
      throw said("price the plan", e);
    }
    return planOf(taskId, brief, asked.get(taskId) ?? [], priced);
  };
  return {
    async prepare(text, files) {
      let intake: IntakeResult;
      try {
        intake = await http.submitIntake(text, [...files]);
      } catch (e) {
        throw said("read this task", e);
      }
      if (!isText(intake?.task_id) || intake.task_id === "" || typeof intake.brief !== "object") {
        throw new TiloApiError(BAD_REPLY, 200, true, true);
      }
      const seen = new Set<string>();
      const questions = (intake.questions ?? []).filter((q) => {
        if (seen.has(q.field)) return false; // the API answers 422 to a field named twice
        seen.add(q.field);
        return true;
      });
      asked.set(intake.task_id, intake.questions ?? []); // every question's text maps its assumption to a field
      let brief: { goal?: unknown; assumptions?: unknown } = intake.brief;
      // Every question skipped, even when there are none: the approaches route wants each one answered or skipped.
      try {
        brief = (
          await http.answerQuestions(
            intake.task_id,
            questions.map((q) => ({ field: q.field, answer: null })),
            {},
          )
        ).brief;
      } catch (e) {
        throw said("record the assumptions", e);
      }
      return price(intake.task_id, brief);
    },
    async revise(taskId, field, answer) {
      let brief: { goal?: unknown; assumptions?: unknown };
      try {
        brief = (await http.answerQuestions(taskId, [{ field, answer }], {})).brief;
      } catch (e) {
        throw said("change that", e);
      }
      return price(taskId, brief);
    },
    async start(plan, repeat) {
      let worldId: string;
      try {
        const { world_id } = await http.approve(plan.taskId, {
          approach_id: plan.approachId,
          budget_cap: plan.cap,
        });
        if (!isText(world_id) || world_id === "")
          throw new TiloApiError(BAD_REPLY, 200, true, true);
        worldId = world_id;
      } catch (e) {
        throw said("start the run", e);
      }
      if (!repeat) return { worldId, repeatRefused: null };
      // The schedule copies what was just approved, so it is posted only after the grant.
      try {
        await http.createSchedule({
          task_id: plan.taskId,
          approach_id: plan.approachId,
          title: plainTitle(`Weekly run: ${plan.approachLabel}`),
          cadence: repeat,
        });
        return { worldId, repeatRefused: null };
      } catch (e) {
        const reason =
          e instanceof TiloApiError && e.message ? e.message : "Tilo could not set it up.";
        return { worldId, repeatRefused: reason };
      }
    },
  };
}
