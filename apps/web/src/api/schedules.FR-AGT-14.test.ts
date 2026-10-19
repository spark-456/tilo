// FR-AGT-14 (PRD 8, "Scheduled runs (Clock Tower)": a weekly schedule fires on time and reuses
// memory), web side. The HttpClient gets four calls over services/api/src/tilo_api/schedules.py:
//   listSchedules()            GET    /schedules            -> {schedules: [view]}, returned as the array
//   createSchedule(req)        POST   /schedules            -> 201 view
//   updateSchedule(id, patch)  PATCH  /schedules/{id}       -> view
//   deleteSchedule(id)         DELETE /schedules/{id}       -> 204, no body
// They are not on the TiloClient interface (like pauseWorld and stopAutopilot). Fetch is mocked at
// the http layer; no network.
import { describe, expect, it, vi } from "vitest";
import { HttpClient, TiloApiError } from "./http";

const BASE = "https://api.test";

type Call = { url: string; init: RequestInit | undefined };

function script(...replies: Array<Response | Error>) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    const next = replies.shift();
    if (!next) throw new Error("unscripted call");
    if (next instanceof Error) throw next;
    return next;
  });
  return { calls, fetch: fetchMock as unknown as typeof fetch };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const VIEW = {
  schedule_id: "sched_a1",
  title: "Weekly competitor scan",
  cadence: { weekday: 0, hour: 9, minute: 0, tz: "Asia/Kolkata" },
  enabled: true,
  next_due: "2026-10-12T03:30:00Z",
  budget_cap: 130,
  last_world_id: null,
  last_slot: null,
  failures: 0,
  last_error: null,
  approved_brief_ref: "w_approved",
  created_at: "2026-10-07T04:00:00Z",
};

const REQ = {
  task_id: "t1",
  approach_id: "thorough",
  title: "Weekly competitor scan",
  cadence: { weekday: 0, hour: 9, minute: 0, tz: "Asia/Kolkata" },
};

// The calls are not on the TiloClient interface; this is the shape the web builder adds to HttpClient.
type SchedulesApi = {
  listSchedules(): Promise<unknown[]>;
  createSchedule(req: typeof REQ): Promise<unknown>;
  updateSchedule(id: string, patch: { enabled?: boolean; title?: string }): Promise<unknown>;
  deleteSchedule(id: string): Promise<void>;
};
const client = (fetch: typeof globalThis.fetch) =>
  new HttpClient({ baseUrl: `${BASE}/`, fetch }) as unknown as SchedulesApi;

describe("FR-AGT-14 web HttpClient: schedule calls", () => {
  it("FR-AGT-14 createSchedule POSTs /schedules with the task, approach, title and cadence as JSON and returns the view", async () => {
    const { calls, fetch } = script(json(VIEW, 201));
    const view = await client(fetch).createSchedule(REQ);
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toBe(`${BASE}/schedules`);
    expect(calls[0]?.init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual(REQ);
    expect(view).toEqual(VIEW);
  });

  it("FR-AGT-14 listSchedules GETs /schedules and returns the schedules array", async () => {
    const { calls, fetch } = script(json({ schedules: [VIEW] }));
    const rows = await client(fetch).listSchedules();
    expect(calls[0]?.url).toBe(`${BASE}/schedules`);
    expect(calls[0]?.init?.method ?? "GET").toBe("GET");
    expect(rows).toEqual([VIEW]);
  });

  it("FR-AGT-14 listSchedules: a reply that is not {schedules: [...]} is an unreadable reply, never an empty list", async () => {
    const { fetch } = script(json({ nope: true }));
    await expect(client(fetch).listSchedules()).rejects.toBeInstanceOf(TiloApiError);
  });

  it("FR-AGT-14 updateSchedule PATCHes /schedules/{id} with only the fields given", async () => {
    const paused = { ...VIEW, enabled: false };
    const { calls, fetch } = script(json(paused));
    const view = await client(fetch).updateSchedule("sched_a1", { enabled: false });
    expect(calls[0]?.url).toBe(`${BASE}/schedules/sched_a1`);
    expect(calls[0]?.init?.method).toBe("PATCH");
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ enabled: false });
    expect(view).toEqual(paused);
  });

  it("FR-AGT-14 deleteSchedule sends DELETE /schedules/{id} and resolves on a 204 with no body", async () => {
    const { calls, fetch } = script(new Response(null, { status: 204 }));
    await expect(client(fetch).deleteSchedule("sched_a1")).resolves.toBeUndefined();
    expect(calls[0]?.url).toBe(`${BASE}/schedules/sched_a1`);
    expect(calls[0]?.init?.method).toBe("DELETE");
  });

  it("FR-AGT-14 schedule ids are URL-encoded in the path", async () => {
    const { calls, fetch } = script(new Response(null, { status: 204 }));
    await client(fetch).deleteSchedule("a/b c");
    expect(calls[0]?.url).toBe(`${BASE}/schedules/a%2Fb%20c`);
  });

  it("FR-AGT-14 createSchedule: 409 'Approve this task's budget first.' is a non-retryable write error carrying that sentence", async () => {
    const { fetch } = script(json({ detail: "Approve this task's budget first." }, 409));
    const error = await client(fetch)
      .createSchedule(REQ)
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(TiloApiError);
    const e = error as TiloApiError;
    expect(e.status).toBe(409);
    expect(e.retryable).toBe(false);
    expect(e.write).toBe(true);
    expect(e.message).toBe("Approve this task's budget first.");
  });

  it("FR-AGT-14 createSchedule: 422 keeps the server's plain sentence; a lost connection is a retryable write error", async () => {
    const said = "Pick a weekday, a time and a time zone that exists.";
    const a = script(json({ detail: said }, 422));
    const e422 = (await client(a.fetch)
      .createSchedule(REQ)
      .catch((e: unknown) => e)) as TiloApiError;
    expect(e422.status).toBe(422);
    expect(e422.message).toBe(said);

    const b = script(new Error("socket closed"));
    const lost = (await client(b.fetch)
      .createSchedule(REQ)
      .catch((e: unknown) => e)) as TiloApiError;
    expect(lost).toBeInstanceOf(TiloApiError);
    expect(lost.retryable).toBe(true);
    expect(lost.write).toBe(true);
  });
});
