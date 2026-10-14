// SIMPLE-RUN-1 acceptance: the one-step start over a fake tilo-api. One POST /intake, every Director question
// skipped in ONE answers call (a field named twice is sent once: the API refuses a repeat with 422), one GET
// approaches, and Start is the approval of the recommended approach's own maximum. Every refusal is in plain words.
import { describe, expect, it, vi } from "vitest";
import { BRIEF_SUPPLIER_COMPARISON } from "../../api/fixtures/brief";
import { TiloApiError } from "../../api/http";
import { createLiveApi } from "./liveApi";
import { MAX_RUN_CREDITS, MIN_RUN_GRANT_CREDITS, oneStepOf } from "./oneStep";

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
  credits: { min: 8, max: 20.5 },
  risks: [],
  skips: [],
};
const QUESTIONS = [
  {
    field: "deadline",
    text: "What date should this meeting be scheduled for?",
    suggested_answers: ["Today"],
  },
  { field: "deadline", text: "When is this due?", suggested_answers: ["By today"] },
  { field: "audience", text: "Who is it for?", suggested_answers: ["The team"] },
];
const BRIEF = {
  ...BRIEF_SUPPLIER_COMPARISON,
  assumptions: [
    { question: "Who is it for?", assumed: "The team" },
    { question: "When is this due?", assumed: "Today" },
    { question: null, assumed: "English" },
  ],
};

function server(over: Record<string, () => Response | Promise<Response>> = {}) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const fetchSpy = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const path = String(url).replace(BASE, "");
    const method = init?.method ?? "GET";
    const raw = init?.body;
    calls.push({
      method,
      path,
      body:
        typeof raw === "string"
          ? JSON.parse(raw)
          : raw instanceof FormData
            ? Object.fromEntries(raw)
            : null,
    });
    const key = `${method} ${path}`;
    if (over[key]) return over[key]();
    if (key === "POST /intake")
      return json({
        task_id: "t_1",
        brief: BRIEF_SUPPLIER_COMPARISON,
        questions: QUESTIONS,
        files: [],
      });
    if (key === "POST /tasks/t_1/answers") return json({ brief: BRIEF });
    if (key === "GET /tasks/t_1/approaches")
      return json({
        task_id: "t_1",
        approaches: [APPROACH],
        recommended: "a_balanced",
        credit_usd: 0.05,
      });
    if (key === "POST /tasks/t_1/approve") return json({ world_id: "w_1" });
    return json({ detail: "Not Found" }, 404);
  });
  const api = createLiveApi({ baseUrl: BASE, fetch: fetchSpy as unknown as typeof fetch });
  const one = oneStepOf(api);
  if (one === null) throw new Error("the live Api has no one-step start");
  return { one, calls };
}

describe("SIMPLE-RUN-1 one-step start over the live Api", () => {
  it("QA-11 requests approaches immediately after saved answers, before the confirm plan resolves", async () => {
    let save!: (value: Response) => void;
    let price!: (value: Response) => void;
    const answers = new Promise<Response>((done) => {
      save = done;
    });
    const approaches = new Promise<Response>((done) => {
      price = done;
    });
    const { one, calls } = server({
      "POST /tasks/t_1/answers": () => answers,
      "GET /tasks/t_1/approaches": () => approaches,
    });
    let ready = false;
    const plan = one.prepare("Plan the offsite", []).then((value) => {
      ready = true;
      return value;
    });
    await vi.waitFor(() => expect(calls.at(-1)?.path).toBe("/tasks/t_1/answers"));
    expect(calls.some((call) => call.path.endsWith("/approaches"))).toBe(false);
    save(json({ brief: BRIEF }));
    await vi.waitFor(() => expect(calls.at(-1)?.path).toBe("/tasks/t_1/approaches"));
    expect(ready).toBe(false);
    price(
      json({ task_id: "t_1", approaches: [APPROACH], recommended: "a_balanced", credit_usd: 0.05 }),
    );
    expect((await plan).taskId).toBe("t_1");
  });

  it("SIMPLE-RUN-1 prepare: one intake, one answers call skipping each distinct question, one approaches read, a priced plan", async () => {
    const { one, calls } = server();
    const plan = await one.prepare("Plan the offsite", []);

    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      "POST /intake",
      "POST /tasks/t_1/answers",
      "GET /tasks/t_1/approaches",
    ]);
    expect(calls[1]?.body, "a field asked twice is skipped once, every answer null").toEqual({
      answers: [
        { field: "deadline", answer: null },
        { field: "audience", answer: null },
      ],
      brief_edits: {},
    });
    expect(plan.taskId).toBe("t_1");
    expect(plan.goal).toBe(BRIEF_SUPPLIER_COMPARISON.goal);
    expect(plan.approachId).toBe("a_balanced");
    expect(plan.cap, "the estimate is under the 30-credit floor, so the floor").toBe(30);
    expect(plan.credits).toEqual({ min: 8, max: 30 });
    expect(plan.time).toBe("2–5 min");
    expect(plan.usd).toBeCloseTo(30 * 0.05);
    expect(plan.lines).toEqual([
      { field: "audience", text: "The team" },
      { field: "deadline", text: "Today" },
      { field: null, text: "English" },
    ]);
  });

  it("SIMPLE-RUN-1 start: Start is the one approve call, with the plan's approach and cap, and answers the world", async () => {
    const { one, calls } = server();
    const plan = await one.prepare("Plan the offsite", []);
    expect(await one.start(plan)).toEqual({ worldId: "w_1", repeatRefused: null });
    const approve = calls.at(-1);
    expect(`${approve?.method} ${approve?.path}`).toBe("POST /tasks/t_1/approve");
    expect(approve?.body).toEqual({ approach_id: "a_balanced", budget_cap: 30 });
  });

  it("SIMPLE-RUN-1 cap: a price above the API's ceiling is asked at the ceiling", async () => {
    const big = { ...APPROACH, credits: { min: 100, max: 4000 } };
    const { one } = server({
      "GET /tasks/t_1/approaches": () =>
        json({ task_id: "t_1", approaches: [big], recommended: "a_balanced", credit_usd: 0.05 }),
    });
    expect((await one.prepare("Big task", [])).cap).toBe(MAX_RUN_CREDITS);
  });

  it("BQ-BUDGET-FLOOR-1 floor: a small estimate is floored, a bigger one is kept, the cap is never above the ceiling", async () => {
    const priced = (credits: { min: number; max: number }, extra: object = {}) =>
      server({
        "GET /tasks/t_1/approaches": () =>
          json({
            task_id: "t_1",
            approaches: [{ ...APPROACH, credits }],
            recommended: "a_balanced",
            credit_usd: 0.005,
            ...extra,
          }),
      }).one;
    const small = await priced({ min: 1, max: 4.2 }).prepare("Tiny", []);
    expect(small.cap).toBe(MIN_RUN_GRANT_CREDITS);
    expect(small.credits).toEqual({ min: 1, max: MIN_RUN_GRANT_CREDITS });
    expect(small.usd).toBeCloseTo(0.15);
    const big = await priced({ min: 40, max: 80.2 }).prepare("Bigger", []);
    expect(big.cap).toBe(81); // above the floor: the estimate stands
    const served = await priced({ min: 1, max: 4 }, { min_grant: 45 }).prepare("Served floor", []);
    expect(served.cap, "the server's own floor wins over the built-in one").toBe(45);
    const over = await priced({ min: 1, max: 4 }, { min_grant: 9000 }).prepare("Silly floor", []);
    expect(over.cap).toBe(MAX_RUN_CREDITS);
  });

  it("SIMPLE-RUN-1 revise: a changed line is answered, then the new brief is priced again", async () => {
    const { one, calls } = server();
    const plan = await one.prepare("Plan the offsite", []);
    const before = calls.length;
    await one.revise(plan.taskId, "audience", "The board");
    expect(calls.slice(before).map((c) => `${c.method} ${c.path}`)).toEqual([
      "POST /tasks/t_1/answers",
      "GET /tasks/t_1/approaches",
    ]);
    expect(calls[before]?.body).toEqual({
      answers: [{ field: "audience", answer: "The board" }],
      brief_edits: {},
    });
  });

  it.each([
    [
      "a list detail (the API's own 422)",
      {
        "POST /tasks/t_1/answers": () =>
          json({ detail: [{ loc: ["body"], msg: "Value error, Pick a real date." }] }, 422),
      },
      /Pick a real date\./,
    ],
    [
      "a plain detail on the answers call",
      {
        "POST /tasks/t_1/answers": () =>
          json({ detail: "Answer only the questions that were asked, each once." }, 422),
      },
      /Answer only the questions that were asked/,
    ],
    [
      "a refusal with no usable words names the step and the status, never the stock sentence",
      { "GET /tasks/t_1/approaches": () => json({ detail: "x".repeat(300) }, 400) },
      /Tilo refused to price the plan \(error 400\)/,
    ],
  ])("SIMPLE-RUN-1 errors: %s is shown in plain words", async (_name, over, expected) => {
    const { one } = server(over);
    const error = await one.prepare("Plan the offsite", []).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(TiloApiError);
    expect((error as TiloApiError).message).toMatch(expected);
    expect((error as TiloApiError).message).not.toBe("Tilo could not accept that.");
  });

  it("SIMPLE-RUN-1 no approach: an empty list stops with a sentence and starts nothing", async () => {
    const { one, calls } = server({
      "GET /tasks/t_1/approaches": () =>
        json({ task_id: "t_1", approaches: [], recommended: "", credit_usd: 0.05 }),
    });
    await expect(one.prepare("Plan the offsite", [])).rejects.toThrow(/nothing was started/);
    expect(calls.some((c) => c.path.endsWith("/approve"))).toBe(false);
  });
});
