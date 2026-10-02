// Fixture values the contracts have no whole-file fixture for. Each is derived from the named
// contract fixture and pinned to it by fixtures.drift.test.ts (PRD-18.3 flow).
import type { ApproachesResult, ClarifyingQuestion, DeliveryResult } from "../client";
import { BRIEF_SUPPLIER_COMPARISON } from "./brief";
import { PLAN_TWO_APPROACHES } from "./plan";

/** The fixture world (layout village_basic and streams/village-basic.jsonl). */
export const FIXTURE_WORLD_ID = "w_village_basic";
export const FIXTURE_TASK_ID = "task_fixture_1";

/** Each skipped-question assumption in the brief fixture becomes a question; [0] is the guess. */
export const FIXTURE_QUESTIONS: ClarifyingQuestion[] =
  BRIEF_SUPPLIER_COMPARISON.assumptions.flatMap((a) =>
    a.question === null
      ? []
      : [{ field: "assumptions", text: a.question, suggested_answers: [a.assumed] }],
  );

/** plan/valid/two_approaches_email_send_gated.json: chosen_approach is the recommendation; 1 credit
 * = US$0.005 (config/prices.yaml credit_usd, PRD 14). */
export const FIXTURE_APPROACHES: Pick<
  ApproachesResult,
  "approaches" | "recommended" | "credit_usd"
> = {
  approaches: [...PLAN_TWO_APPROACHES.approaches],
  recommended: PLAN_TWO_APPROACHES.chosen_approach,
  credit_usd: 0.005,
};

/** streams/village-basic.jsonl seq 25 (artifact.created) and 41 (artifact.delivered), seq 44
 * (world.completed credits_used) and meter/valid/live_run.json time_saved low and high. */
export const FIXTURE_DELIVERY: DeliveryResult = {
  world_id: FIXTURE_WORLD_ID,
  artifacts: [{ id: "art_triage_list", title: "Triage list", kind: "document", version: 1 }],
  credits_used: 13,
  time_saved: { low_min: 8, high_min: 18 },
};
