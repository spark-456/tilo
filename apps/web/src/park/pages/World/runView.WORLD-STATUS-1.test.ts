// WORLD-STATUS-1 (FR-WLD-05, FR-WLD-09, FR-HIL-02; HR-1, HR-5): the World page's one status line follows the latest
// recorded state. Once the questions were answered or defaulted and the run was approved, it never says the Director
// is waiting for answers; before the first agent event of a started run it says the team is getting ready.
import { describe, expect, it } from "vitest";
import { runView } from "./runView";
import type { RunEvent } from "./useRunEvents";

let seq = 0;
const ev = (type: string, summary: string, data: unknown = {}): RunEvent => ({
  seq: ++seq,
  type,
  ts: `2026-10-15T13:${String(seq).padStart(2, "0")}:00.000Z`,
  credits: 0,
  summary,
  data,
});
const asked = () =>
  ev("plan.questions_asked", "The Director has 3 questions.", { question_count: 3 });
const granted = () =>
  ev("budget.granted", "You approved a budget of 40 credits.", { granted: 40, cap: 40 });
const started = () =>
  ev("world.started", "Work started with a budget of 40 credits.", { budget_cap: 40 });

describe("FR_WLD_05 WORLD-STATUS-1 the status line follows the recorded run state", () => {
  it("FR_HIL_02 still waits for answers while questions are asked and nothing followed", () => {
    seq = 0;
    expect(runView([asked()])).toMatchObject({
      phase: "planning",
      line: "The Director is waiting for your answers (3 questions).",
    });
  });

  it("FR_HIL_02 never waits for answers once the owner approved after the questions", () => {
    seq = 0;
    const view = runView([asked(), granted()]);
    expect(view.line).not.toMatch(/waiting for your answers/i);
    expect(view).toMatchObject({ phase: "starting", line: "Starting: the team is getting ready." });
  });

  it("FR_HIL_02 an approval.resolved or a question.answered after the questions also ends the wait", () => {
    seq = 0;
    expect(runView([asked(), ev("question.answered", "You answered.")]).line).toBe(
      "Starting: the team is getting ready.",
    );
    seq = 0;
    expect(runView([asked(), ev("approval.resolved", "You approved.")]).phase).toBe("starting");
  });

  it("FR_WLD_05 a started run says the team is getting ready until the first agent event", () => {
    seq = 0;
    const events = [asked(), granted(), started()];
    expect(runView(events)).toMatchObject({
      phase: "working",
      line: "Starting: the team is getting ready.",
    });
    const first = [...events, ev("agent.spawned", "The Director joined the team.", { unit: null })];
    expect(runView(first).line).toBe("Working: The Director joined the team.");
  });

  it("FR_WLD_05 a plan that is ready still reads as ready, not as starting", () => {
    seq = 0;
    const planned = ev("world.planned", "The Director planned 3 units.", { unit_count: 3 });
    expect(runView([asked(), granted(), planned]).phase).toBe("ready");
  });
});
