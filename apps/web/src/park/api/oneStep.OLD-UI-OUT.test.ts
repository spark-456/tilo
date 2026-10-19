// OLD-UI-OUT wave 1 / FR-AGT-14 (ported from the retired S-03 tests): the weekly schedule is posted once, only after
// the budget grant and the start succeeded, with the chosen approach, a plain title and the cadence. A refused
// schedule never undoes the run: the start answers the world and the plain reason.
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
  summary: "s",
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
const CADENCE = { weekday: 0, hour: 9, minute: 0, tz: "Asia/Kolkata" };

function rig(over: Record<string, () => Response> = {}) {
  const calls: { key: string; body: unknown }[] = [];
  const fetchSpy = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${String(url).replace(BASE, "")}`;
    calls.push({ key, body: typeof init?.body === "string" ? JSON.parse(init.body) : null });
    if (over[key]) return over[key]();
    if (key === "POST /intake")
      return json({ task_id: "t_1", brief: BRIEF_SUPPLIER_COMPARISON, questions: [], files: [] });
    if (key === "POST /tasks/t_1/answers") return json({ brief: BRIEF_SUPPLIER_COMPARISON });
    if (key === "GET /tasks/t_1/approaches")
      return json({
        task_id: "t_1",
        approaches: [APPROACH],
        recommended: "a_balanced",
        credit_usd: 0.05,
      });
    if (key === "POST /tasks/t_1/approve") return json({ world_id: "w_1" });
    if (key === "POST /schedules")
      return json({
        schedule_id: "s_1",
        title: "x",
        cadence: CADENCE,
        enabled: true,
        next_due: null,
      });
    return json({ detail: "Not Found" }, 404);
  });
  const api = createLiveApi({ baseUrl: BASE, fetch: fetchSpy as unknown as typeof fetch });
  const one = oneStepOf(api);
  if (one === null) throw new Error("no one-step start");
  return { one, calls };
}

describe("FR-AGT-14 one-step start: Repeat weekly", () => {
  it("posts one schedule after the approve, with the approach, a plain title and the cadence", async () => {
    const { one, calls } = rig();
    const plan = await one.prepare("Compare suppliers", []);
    const started = await one.start(plan, CADENCE);
    expect(started).toEqual({ worldId: "w_1", repeatRefused: null });
    const keys = calls.map((c) => c.key);
    expect(keys.indexOf("POST /schedules")).toBeGreaterThan(
      keys.indexOf("POST /tasks/t_1/approve"),
    );
    expect(keys.filter((k) => k === "POST /schedules")).toHaveLength(1);
    expect(calls.find((c) => c.key === "POST /schedules")?.body).toEqual({
      task_id: "t_1",
      approach_id: "a_balanced",
      title: "Weekly run: Balanced",
      cadence: CADENCE,
    });
  });

  it("posts no schedule when the repeat is off", async () => {
    const { one, calls } = rig();
    const plan = await one.prepare("Compare suppliers", []);
    await one.start(plan, null);
    await one.start(plan);
    expect(calls.some((c) => c.key === "POST /schedules")).toBe(false);
  });

  it("a refused schedule (409) keeps the started run and returns the plain sentence", async () => {
    const { one } = rig({
      "POST /schedules": () => json({ detail: "This task already has a schedule." }, 409),
    });
    const plan = await one.prepare("Compare suppliers", []);
    const started = await one.start(plan, CADENCE);
    expect(started.worldId).toBe("w_1");
    expect(started.repeatRefused).toBe("This task already has a schedule.");
  });

  it("if the start itself fails, no schedule is posted", async () => {
    const { one, calls } = rig({
      "POST /tasks/t_1/approve": () =>
        json({ detail: "One run may use at most 300 credits." }, 422),
    });
    const plan = await one.prepare("Compare suppliers", []);
    await expect(one.start(plan, CADENCE)).rejects.toThrow(/at most 300 credits/);
    expect(calls.some((c) => c.key === "POST /schedules")).toBe(false);
  });
});
