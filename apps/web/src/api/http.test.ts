import type { Card, Event } from "@tilo/contracts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { chooseClient } from "./config";
import { FixtureClient } from "./fixtureClient";
import { CARDS_VALID } from "./fixtures/cards";
import { EVENTS_VILLAGE_BASIC } from "./fixtures/events";
import { HttpClient, TiloApiError } from "./http";

const BASE = "https://api.test";
type Call = { url: string; init: RequestInit | undefined };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** A scripted fetch: each call takes the next reply (a Response, or an Error to throw). */
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

const client = (fetch: typeof globalThis.fetch, pollMs = 1000) =>
  new HttpClient({ baseUrl: `${BASE}/`, fetch, pollMs });

describe("CL-INT-3: HttpClient calls the services/api routes", () => {
  it("submitIntake posts multipart text and files and maps the response", async () => {
    const brief = EVENTS_VILLAGE_BASIC; // any JSON stands in for the brief
    const { calls, fetch } = script(
      json(
        {
          task_id: "t1",
          world_id: "w1",
          run_id: "r1",
          brief,
          questions: [{ field: "audience", text: "Who?", suggested_answers: ["Finance"] }],
          files: [
            {
              filename: "a.pdf",
              status: "ok",
              safety_flagged: false,
              safety_reason: null,
              error: null,
            },
            {
              filename: "b.pdf",
              status: "failed",
              safety_flagged: false,
              safety_reason: null,
              error: "boom at x.py:3",
            },
            {
              filename: "c.pdf",
              status: "ok",
              safety_flagged: true,
              safety_reason: "injection",
              error: null,
            },
          ],
        },
        201,
      ),
    );
    const result = await client(fetch).submitIntake("Compare quotes", [new File(["x"], "a.pdf")]);
    expect(calls[0]?.url).toBe(`${BASE}/intake`);
    expect(calls[0]?.init?.method).toBe("POST");
    const form = calls[0]?.init?.body as FormData;
    expect(form.get("text")).toBe("Compare quotes");
    expect((form.getAll("files")[0] as File).name).toBe("a.pdf");
    expect(result.task_id).toBe("t1");
    expect(result.questions[0]?.field).toBe("audience");
    expect(result.files.map((f) => f.name)).toEqual(["a.pdf", "b.pdf", "c.pdf"]);
    expect(result.files[1]).toMatchObject({ status: "failed", safety_flagged: false });
    expect(result.files[1]?.reason).not.toContain("boom"); // server error text is not shown
    expect(result.files[2]).toMatchObject({ safety_flagged: true });
  });

  it("answerQuestions, getApproaches and approve use the task routes", async () => {
    const { calls, fetch } = script(
      json({ brief: { goal: "g" } }),
      json({ task_id: "t1", approaches: [], recommended: "quick", credit_usd: 0.005 }),
      json({ world_id: "w1" }),
    );
    const c = client(fetch);
    const answered = await c.answerQuestions("t 1", [{ field: "audience", answer: null }], {
      audience: "Finance",
    });
    expect(answered).toEqual({ brief: { goal: "g" } });
    expect(calls[0]?.url).toBe(`${BASE}/tasks/t%201/answers`);
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({
      answers: [{ field: "audience", answer: null }],
      brief_edits: { audience: "Finance" },
    });
    expect((await c.getApproaches("t1")).recommended).toBe("quick");
    expect(calls[1]?.url).toBe(`${BASE}/tasks/t1/approaches`);
    expect(await c.approve("t1", { approach_id: "quick", budget_cap: 45 })).toEqual({
      world_id: "w1",
    });
    expect(calls[2]?.url).toBe(`${BASE}/tasks/t1/approve`);
    expect(JSON.parse(String(calls[2]?.init?.body))).toEqual({
      approach_id: "quick",
      budget_cap: 45,
    });
    expect(new Headers(calls[2]?.init?.headers).get("content-type")).toBe("application/json");
  });

  it("listCards, answerCard, getDelivery and pauseWorld use the world routes", async () => {
    const card: Card = { ...(CARDS_VALID[0] as Card), world_id: "w1" };
    const delivery = { world_id: "w1", artifacts: [], credits_used: 3, time_saved: null };
    const { calls, fetch } = script(
      json([card]),
      json({ outcome: "answered" }),
      json(delivery),
      json({ paused: true }),
    );
    const c = client(fetch);
    expect(await c.listCards("w1")).toEqual([card]);
    expect(calls[0]?.url).toBe(`${BASE}/worlds/w1/cards`);
    await c.answerCard(card.id, { option_id: "approve", context: "ignored" });
    expect(calls[1]?.url).toBe(`${BASE}/worlds/w1/cards/${card.id}/answer`);
    expect(JSON.parse(String(calls[1]?.init?.body))).toEqual({ option: "approve" });
    expect(await c.getDelivery("w1")).toEqual(delivery);
    expect(calls[2]?.url).toBe(`${BASE}/worlds/w1/delivery`);
    await c.pauseWorld("w1");
    expect(calls[3]?.url).toBe(`${BASE}/worlds/w1/pause`);
    expect(calls[3]?.init?.method).toBe("POST");
  });

  it("answerCard for a card it never listed says so, without calling the server", async () => {
    const { calls, fetch } = script();
    await expect(
      client(fetch).answerCard("c_unknown", { option_id: "approve" }),
    ).rejects.toMatchObject({
      retryable: false,
    });
    expect(calls).toHaveLength(0);
  });

  it("getLayout has no API route yet: a plain, non-retryable error and no request", async () => {
    const { calls, fetch } = script();
    await expect(client(fetch).getLayout("w1")).rejects.toMatchObject({ retryable: false });
    expect(calls).toHaveLength(0);
  });
});

describe("CL-INT-3: error mapping", () => {
  const fail = (reply: Response | Error) => client(script(reply).fetch).getApproaches("t1");

  it("a 4xx gives the server's own sentence as the reason, never retryable", async () => {
    const error = await fail(json({ detail: "Answer or skip every question first." }, 409)).catch(
      (e) => e,
    );
    expect(error).toBeInstanceOf(TiloApiError);
    expect(error).toMatchObject({
      message: "Answer or skip every question first.",
      status: 409,
      retryable: false,
    });
  });

  it("an intake 422 reads its {error} sentence", async () => {
    const error = await client(
      script(json({ error: "7 files attached; the limit is 5." }, 422)).fetch,
    )
      .submitIntake("t", [])
      .catch((e) => e);
    expect(error.message).toBe("7 files attached; the limit is 5.");
  });

  it("text that is not meant for people is replaced by a plain sentence", async () => {
    for (const reply of [
      json({ detail: [{ loc: ["body", "x"], msg: "field required" }] }, 422),
      json({ detail: "Not Found" }, 404),
      json({ outcome: "rejected", reason: "channel_not_permitted" }, 403),
      new Response("<html>Traceback (most recent call last)</html>", { status: 400 }),
      json({ detail: "x".repeat(500) }, 400),
    ]) {
      const error = await fail(reply).catch((e) => e);
      expect(error).toBeInstanceOf(TiloApiError);
      expect(error.retryable).toBe(false);
      expect(error.message).toMatch(/^[A-Z][^<>{}]{3,120}\.$/);
      expect(error.message).not.toMatch(/Traceback|field required|channel_not_permitted|xxxx/);
    }
  });

  it("a 5xx is retryable and never shows server text", async () => {
    const error = await fail(json({ detail: "Traceback in tilo_api/runs.py" }, 503)).catch(
      (e) => e,
    );
    expect(error).toMatchObject({ status: 503, retryable: true });
    expect(error.message).not.toContain("Traceback");
  });

  it("a network failure is retryable and never shows the cause", async () => {
    const error = await fail(new TypeError("connect ECONNREFUSED 10.0.0.5:8080")).catch((e) => e);
    expect(error).toMatchObject({ status: null, retryable: true });
    expect(error.message).not.toContain("ECONNREFUSED");
  });

  it("a 2xx that is not the expected JSON is retryable", async () => {
    const error = await fail(new Response("oops", { status: 200 })).catch((e) => e);
    expect(error).toMatchObject({ retryable: true });
  });
});

describe("CL-INT-3 / FR-WLD-05: subscribeEvents polls GET /worlds/{id}/events with a seq cursor", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  // The owner's view omits v, world_id, run_id and item (services/api redaction.py).
  const view = (e: Event) => {
    const { v: _v, world_id: _w, run_id: _r, item: _i, ...rest } = e;
    return rest;
  };
  const sample = [...EVENTS_VILLAGE_BASIC].sort((a, b) => a.seq - b.seq).slice(0, 5);
  const settle = async (ms: number) => {
    await vi.advanceTimersByTimeAsync(ms);
  };

  it("delivers in seq order, fills the fields the view omits and dedupes by id", async () => {
    const { calls, fetch } = script(
      json({ events: [sample[2], sample[0], sample[1]].map((e) => view(e as Event)) }),
      json({ events: sample.slice(0, 4).map((e) => view(e)) }), // overlaps: 0..2 repeat
    );
    const got: Event[] = [];
    const stop = client(fetch).subscribeEvents("w1", (e) => got.push(e));
    await settle(0);
    expect(got.map((e) => e.seq)).toEqual(sample.slice(0, 3).map((e) => e.seq));
    expect(got[0]).toMatchObject({ v: "1.0", world_id: "w1", item: null, id: sample[0]?.id });
    await settle(1000);
    expect(got.map((e) => e.seq)).toEqual(sample.slice(0, 4).map((e) => e.seq));
    expect(calls.map((c) => c.url)).toEqual([
      `${BASE}/worlds/w1/events`,
      `${BASE}/worlds/w1/events`,
    ]);
    stop();
  });

  it("resumes after a failed poll without repeating or skipping an event", async () => {
    const { fetch } = script(
      json({ events: sample.slice(0, 2).map((e) => view(e)) }),
      new TypeError("offline"),
      json({ detail: "boom" }, 503),
      json({ events: sample.slice(0, 5).map((e) => view(e)) }),
    );
    const got: number[] = [];
    const stop = client(fetch).subscribeEvents("w1", (e) => got.push(e.seq));
    await settle(0);
    expect(got).toHaveLength(2);
    await settle(10_000); // failed polls back off, then the next good one catches up
    expect(got).toEqual(sample.map((e) => e.seq));
    stop();
  });

  it("stops after the world completes or fails, on a non-retryable error, and on unsubscribe", async () => {
    const done = { ...view(sample[0] as Event), seq: 99, id: "01JDONE", type: "world.completed" };
    const a = script(json({ events: [done] }), json({ events: [] }));
    client(a.fetch).subscribeEvents("w1", () => undefined);
    await settle(5000);
    expect(a.calls).toHaveLength(1);

    const b = script(json({ detail: "Not Found" }, 404), json({ events: [] }));
    client(b.fetch).subscribeEvents("w1", () => undefined);
    await settle(5000);
    expect(b.calls).toHaveLength(1);

    const c = script(json({ events: [] }), json({ events: [] }));
    const stop = client(c.fetch).subscribeEvents("w1", () => undefined);
    await settle(0);
    stop();
    await settle(5000);
    expect(c.calls).toHaveLength(1);
  });

  it("drops malformed rows and keeps unknown event types (HR-5: they go to the Trace)", async () => {
    const unknown = {
      ...view(sample[0] as Event),
      seq: 50,
      id: "01JUNKNOWN",
      type: "future.thing",
    };
    const { fetch } = script(json({ events: [null, { seq: "x" }, { id: "no-seq" }, unknown] }));
    const got: Event[] = [];
    client(fetch).subscribeEvents("w1", (e) => got.push(e));
    await settle(0);
    expect(got.map((e) => e.type)).toEqual(["future.thing"]);
  });
});

describe("CL-INT-3: the client is chosen by config", () => {
  it("VITE_TILO_API_URL selects the HTTP client; without it the fixture client stays", () => {
    expect(chooseClient({ apiUrl: undefined, search: "" })).toBeInstanceOf(FixtureClient);
    expect(chooseClient({ apiUrl: "  ", search: "" })).toBeInstanceOf(FixtureClient);
    expect(chooseClient({ apiUrl: "http://localhost:8080", search: "" })).toBeInstanceOf(
      HttpClient,
    );
  });

  it("the fixture client keeps its delay and speed params", () => {
    const c = chooseClient({ apiUrl: undefined, search: "?speed=4&client_delay_ms=5" });
    expect(c).toBeInstanceOf(FixtureClient);
    expect((c as FixtureClient).replaySpeed).toBe(4);
  });
});
