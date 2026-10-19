// FT-SUP-2: approaches latency and visible streamed steps
import { describe, expect, it, vi } from "vitest";
import { BRIEF_SUPPLIER_COMPARISON } from "../../api/fixtures/brief";
import { createLiveApi } from "./liveApi";
import { oneStepOf } from "./oneStep";

const BASE = "https://api.example.test";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const APPROACH = {
  id: "a_balanced",
  label: "Balanced",
  summary: "Read the sources, then write.",
  dimensions: {
    depth: "standard",
    sources: "web",
    parallelism: "single",
    verification: "light",
    output_format: "document",
  },
  time: { min_s: 120, max_s: 300 },
  credits: { min: 8, max: 20 },
  risks: [],
  skips: [],
};

function server(questions: { field: string; text: string; suggested_answers: string[] }[] = []) {
  const calls: { method: string; path: string }[] = [];
  const fetchSpy = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const path = String(url).replace(BASE, "");
    const method = init?.method ?? "GET";
    calls.push({ method, path });
    const key = `${method} ${path}`;
    if (key === "POST /intake")
      return json({
        task_id: "t_1",
        brief: BRIEF_SUPPLIER_COMPARISON,
        questions,
        files: [],
      });
    if (key === "POST /tasks/t_1/answers") return json({ brief: BRIEF_SUPPLIER_COMPARISON });
    if (key === "GET /tasks/t_1/approaches")
      return json({
        task_id: "t_1",
        approaches: [APPROACH],
        recommended: "a_balanced",
        credit_usd: 0.05,
      });
    return json({ detail: "Not Found" }, 404);
  });
  const api = createLiveApi({ baseUrl: BASE, fetch: fetchSpy as unknown as typeof fetch });
  const one = oneStepOf(api);
  if (one === null) throw new Error("the live Api has no one-step start");
  return { one, calls };
}

describe("FT-SUP-2 approaches latency and visible streamed steps", () => {
  it("FT-SUP-2 skips redundant answerQuestions call when intake returns no questions", async () => {
    const { one, calls } = server([]); // zero questions
    const steps: string[] = [];
    const plan = await one.prepare("Research competitors", [], undefined, (step) => {
      steps.push(step);
    });

    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      "POST /intake",
      "GET /tasks/t_1/approaches",
    ]);
    expect(plan.taskId).toBe("t_1");
    expect(plan.approachId).toBe("a_balanced");
    expect(steps).toEqual([
      "Reading your task...",
      "Structuring brief...",
      "Pricing approaches...",
    ]);
  });

  it("FT-SUP-2 reports visible streamed steps when questions are present", async () => {
    const { one, calls } = server([
      { field: "audience", text: "Who is it for?", suggested_answers: ["The team"] },
    ]);
    const steps: string[] = [];
    const plan = await one.prepare("Research competitors", [], undefined, (step) => {
      steps.push(step);
    });

    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      "POST /intake",
      "POST /tasks/t_1/answers",
      "GET /tasks/t_1/approaches",
    ]);
    expect(plan.taskId).toBe("t_1");
    expect(steps).toEqual([
      "Reading your task...",
      "Structuring brief...",
      "Pricing approaches...",
    ]);
  });
});
