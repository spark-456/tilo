import type { Card, Event } from "@tilo/contracts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { chooseClient } from "./config";
import { FixtureClient } from "./fixtureClient";
import { CARDS_VALID } from "./fixtures/cards";
import { EVENTS_VILLAGE_BASIC } from "./fixtures/events";
import { LAYOUT_VILLAGE_BASIC } from "./fixtures/layout";
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
    expect(result.files[2]).toMatchObject({
      safety_flagged: true,
      reason: "The safety check flagged this file.", // the provider's own text is not shown
    });
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

  it("FR-HIL-07 stopAutopilot posts to the world's stop route and returns the API's own count", async () => {
    const body = { stopped: 2, already_l1: 1, confirmations: [{ channel: "web" }], pending: 0 };
    const { calls, fetch } = script(json(body), json({ ...body, pending: 1 }, 202));
    const c = client(fetch);
    expect(await c.stopAutopilot("w 1")).toEqual(body);
    expect(calls[0]?.url).toBe(`${BASE}/worlds/w%201/autopilot/stop`);
    expect(calls[0]?.init?.method).toBe("POST");
    expect((await c.stopAutopilot("w 1")).pending).toBe(1); // 202: still being recorded
  });

  it("FR-HIL-07 stopAutopilot refuses a reply that is not the documented shape and keeps a 403's words", async () => {
    const { fetch } = script(json({ stopped: "two" }), json({ detail: "not the owner" }, 403));
    const c = client(fetch);
    await expect(c.stopAutopilot("w1")).rejects.toMatchObject({
      message: expect.stringMatching(/could not read/),
    });
    await expect(c.stopAutopilot("w1")).rejects.toMatchObject({ status: 403, retryable: false });
  });

  // FR-HIL-11: the answer records the channel it came from, so a phone answer reads "mobile_web".
  describe("FR_HIL_11 answerCard names the channel", () => {
    const phone = (matches: boolean) =>
      vi.stubGlobal("window", { matchMedia: (q: string) => ({ matches, media: q }) });
    afterEach(() => vi.unstubAllGlobals());
    const sent = async (matches: boolean | null, channels: Card["answer_channels"]) => {
      if (matches !== null) phone(matches);
      const card: Card = { ...(CARDS_VALID[0] as Card), world_id: "w1", answer_channels: channels };
      const { calls, fetch } = script(json([card]), json({ outcome: "answered" }));
      const c = client(fetch);
      await c.listCards("w1");
      await c.answerCard(card.id, { option_id: "approve" });
      return JSON.parse(String(calls[1]?.init?.body));
    };
    it("sends mobile_web from a phone-width window when the card lists it", async () => {
      expect(await sent(true, ["web", "mobile_web"])).toEqual({
        option: "approve",
        channel: "mobile_web",
      });
    });
    it("sends nothing extra (web) on a desktop-width window, or with no window", async () => {
      expect(await sent(false, ["web", "mobile_web"])).toEqual({ option: "approve" });
      expect(await sent(null, ["web", "mobile_web"])).toEqual({ option: "approve" });
    });
    it("stays web on a phone for a card that does not list mobile_web", async () => {
      expect(await sent(true, ["web"])).toEqual({ option: "approve" });
    });
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

  // A row as an up-to-date server stores it (CL-INT-4): the client hands on only whole rows.
  const row = (type: string, seq: number, world = "w1") => ({
    v: "1.0",
    id: `e${seq}`,
    seq,
    type,
    world_id: world,
    run_id: "r1",
    item: null,
  });
  const eventsOf = (world: string, ...types: string[]) =>
    json({ events: types.map((t, i) => row(t, i + 1, world)) });
  const events = (...types: string[]) => eventsOf("w1", ...types);

  it("FR-WLD-05 getLayout reads the events first and asks for the layout only once world.started is on record", async () => {
    const { calls, fetch } = script(
      eventsOf("w 1", "budget.granted"),
      eventsOf("w 1", "budget.granted", "world.started"),
      json(LAYOUT_VILLAGE_BASIC),
    );
    const c = client(fetch, 1);
    await expect(c.getLayout("w 1")).resolves.toMatchObject({ world_id: "w_village_basic" });
    expect(calls.map((x) => x.url)).toEqual([
      `${BASE}/worlds/w%201/events`,
      `${BASE}/worlds/w%201/events`,
      `${BASE}/worlds/w%201/layout`,
    ]);
  });

  it("FR-WLD-05 getLayout keeps a built layout and shares one call per world", async () => {
    const { calls, fetch } = script(events("world.started"), json(LAYOUT_VILLAGE_BASIC));
    const c = client(fetch, 1);
    const [a, b] = await Promise.all([c.getLayout("w1"), c.getLayout("w1")]);
    expect(a).toBe(b);
    await c.getLayout("w1");
    expect(calls).toHaveLength(2);
  });

  it("FR-WLD-05 getLayout polls a 404 for a moment, then says the world is not built", async () => {
    const { calls, fetch } = script(
      events("world.started"),
      json({ detail: "Not Found" }, 404),
      json(LAYOUT_VILLAGE_BASIC),
    );
    await expect(client(fetch, 1).getLayout("w1")).resolves.toBeDefined();
    expect(calls).toHaveLength(3);
    const never = script(
      events("world.started"),
      ...Array.from({ length: 5 }, () => json({ detail: "Not Found" }, 404)),
    );
    await expect(client(never.fetch, 1).getLayout("w1")).rejects.toMatchObject({
      status: 404,
      retryable: true,
    });
  });

  it("FR-WLD-05 getLayout rejects plainly when the run failed before it built a world, and a retry asks again", async () => {
    const failed = script(events("world.failed"));
    const c = client(failed.fetch, 1);
    await expect(c.getLayout("w1")).rejects.toMatchObject({ retryable: false });
    expect(failed.calls).toHaveLength(1);
    const again = script(json({ events: [] }, 500));
    await expect(client(again.fetch, 1).getLayout("w1")).rejects.toMatchObject({ retryable: true });
  });

  it("FR-WLD-05 getLayout refuses a reply that is not a layout", async () => {
    const { fetch } = script(events("world.started"), json({ nothing: true }));
    await expect(client(fetch, 1).getLayout("w1")).rejects.toMatchObject({ retryable: true });
  });

  it("FR-WLD-05 an unknown world: one 404 from the events, polling stops, getLayout rejects without asking again", async () => {
    vi.useFakeTimers();
    try {
      const { calls, fetch } = script(json({ detail: "Not Found" }, 404));
      const c = client(fetch, 1);
      const errors: Array<number | null> = [];
      const stop = c.subscribeEvents(
        "nope",
        () => undefined,
        (e) => errors.push(e.status),
      );
      const layout = c.getLayout("nope").catch((e: unknown) => e);
      await vi.advanceTimersByTimeAsync(30_000);
      expect(errors).toEqual([404]);
      expect(await layout).toMatchObject({ status: 404, retryable: false });
      expect(calls).toHaveLength(1); // the page's subscription is the only request
      expect(vi.getTimerCount()).toBe(0);
      stop();
    } finally {
      vi.useRealTimers();
    }
  });

  it("FR-WLD-05 getLayout waits on the page's own subscription: no events request and no timer of its own", async () => {
    vi.useFakeTimers();
    try {
      const { calls, fetch } = script(
        events("budget.granted"),
        events("budget.granted", "world.started"),
        json(LAYOUT_VILLAGE_BASIC),
      );
      const c = client(fetch, 1000);
      const stop = c.subscribeEvents("w1", () => undefined);
      const layout = c.getLayout("w1");
      await vi.advanceTimersByTimeAsync(1000);
      await expect(layout).resolves.toBeDefined();
      expect(calls.map((x) => x.url.split("/").pop())).toEqual(["events", "events", "layout"]);
      stop();
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("FR-WLD-05 a getLayout nobody awaits leaves no timer behind once it ends", async () => {
    vi.useFakeTimers();
    try {
      const { fetch } = script(events("world.started"), json(LAYOUT_VILLAGE_BASIC));
      await client(fetch, 1000).getLayout("w1");
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  describe("#264 getLayout stops polling when the pages asking for it let go", () => {
    /** A run that never starts: every events poll is empty, so getLayout waits on it. */
    const stuck = () => {
      const urls: string[] = [];
      const fetch = vi.fn(async (url: string | URL | Request) => {
        urls.push(String(url));
        return json({ events: [] });
      }) as unknown as typeof globalThis.fetch;
      return { urls, fetch };
    };

    it("aborting the only caller ends the events polling and the wait", async () => {
      vi.useFakeTimers();
      try {
        const { urls, fetch } = stuck();
        const c = client(fetch, 1000);
        const stop = new AbortController();
        const layout = c.getLayout("w1", stop.signal).catch((e: unknown) => e);
        await vi.advanceTimersByTimeAsync(3000);
        const before = urls.length;
        expect(before).toBeGreaterThan(1);
        stop.abort();
        await expect(layout).resolves.toBeInstanceOf(TiloApiError);
        await vi.advanceTimersByTimeAsync(10_000);
        expect(urls).toHaveLength(before);
        expect(vi.getTimerCount()).toBe(0);
      } finally {
        vi.useRealTimers();
      }
    });

    it("a second caller keeps the shared wait alive until it lets go too", async () => {
      vi.useFakeTimers();
      try {
        const { urls, fetch } = stuck();
        const c = client(fetch, 1000);
        const first = new AbortController();
        const second = new AbortController();
        const a = c.getLayout("w1", first.signal);
        const b = c.getLayout("w1", second.signal);
        expect(a).toBe(b);
        first.abort();
        await vi.advanceTimersByTimeAsync(3000);
        const mid = urls.length;
        expect(mid).toBeGreaterThan(2); // still polling for the second
        second.abort();
        await expect(b).rejects.toBeInstanceOf(TiloApiError);
        await vi.advanceTimersByTimeAsync(10_000);
        expect(urls).toHaveLength(mid);
      } finally {
        vi.useRealTimers();
      }
    });

    it("a call after the last one let go starts afresh, and stopping the old one does not end it", async () => {
      vi.useFakeTimers();
      try {
        const { fetch } = script(events(), events("world.started"), json(LAYOUT_VILLAGE_BASIC));
        const c = client(fetch, 1000);
        const gone = new AbortController();
        const old = c.getLayout("w1", gone.signal).catch((e: unknown) => e);
        gone.abort();
        await old;
        const fresh = c.getLayout("w1", new AbortController().signal);
        await vi.advanceTimersByTimeAsync(1000);
        await expect(fresh).resolves.toBeDefined();
      } finally {
        vi.useRealTimers();
      }
    });

    it("a signal that is already aborted asks for nothing", async () => {
      const { urls, fetch } = stuck();
      const c = client(fetch, 1);
      const stop = new AbortController();
      stop.abort();
      await expect(c.getLayout("w1", stop.signal)).rejects.toBeInstanceOf(TiloApiError);
      await new Promise((r) => setTimeout(r, 20));
      expect(urls).toEqual([]);
    });
  });

  it("#264 a world that answered 404 is known again once a later poll finds it", async () => {
    const { fetch } = script(json({ detail: "Not Found" }, 404), events("world.started"));
    const c = client(fetch, 1);
    c.subscribeEvents(
      "w1",
      () => undefined,
      () => undefined,
    );
    await vi.waitFor(() => expect(c.isWorldMissing("w1")).toBe(true));
    const seen = vi.fn();
    c.onWorldMissing(seen);
    const stop = c.subscribeEvents("w1", () => undefined);
    await vi.waitFor(() => expect(c.isWorldMissing("w1")).toBe(false));
    expect(seen).toHaveBeenCalled();
    stop();
  });

  it("#258 getApproaches calls that overlap share one request; a later call asks again", async () => {
    const reply = { task_id: "t1", approaches: [], recommended: "a", credit_usd: 1 };
    const { calls, fetch } = script(json(reply), json(reply));
    const c = client(fetch);
    const [a, b] = await Promise.all([c.getApproaches("t1"), c.getApproaches("t1")]);
    expect(a).toBe(b);
    expect(calls).toHaveLength(1);
    await c.getApproaches("t1");
    expect(calls).toHaveLength(2);
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

  it("a card answer's reason code becomes a fixed sentence", async () => {
    const card: Card = { ...(CARDS_VALID[0] as Card), world_id: "w1" };
    const answer = async (status: number, reason: string) => {
      const c = client(script(json([card]), json({ outcome: "rejected", reason }, status)).fetch);
      await c.listCards("w1");
      return c.answerCard(card.id, { option_id: "approve" }).catch((e) => e);
    };
    expect((await answer(400, "already_resolved")).message).toBe("This card was already answered.");
    expect((await answer(400, "pin_required")).message).toMatch(/PIN/);
    expect((await answer(403, "forbidden")).message).toMatch(/access/);
    expect((await answer(404, "card_not_found")).message).toMatch(/find that card/);
    expect((await answer(400, "something_new")).message).toBe("Tilo could not accept that.");
  });

  it("marks failures of writes, so a retryable one is not reported as 'nothing changed'", async () => {
    const write = await client(script(new TypeError("offline")).fetch)
      .approve("t1", { approach_id: "quick", budget_cap: 5 })
      .catch((e) => e);
    expect(write).toMatchObject({ retryable: true, write: true });
    const read = await fail(new TypeError("offline")).catch((e) => e);
    expect(read).toMatchObject({ retryable: true, write: false });
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

  // An up-to-date server (CL-INT-4) returns the stored event whole, for the requested world.
  const view = (e: Event): Event => ({ ...e, world_id: "w1" });
  const without = (e: Event, ...keys: string[]) =>
    Object.fromEntries(Object.entries(view(e)).filter(([k]) => !keys.includes(k)));
  const sample = [...EVENTS_VILLAGE_BASIC].sort((a, b) => a.seq - b.seq).slice(0, 5);
  const settle = async (ms: number) => {
    await vi.advanceTimersByTimeAsync(ms);
  };

  it("delivers in seq order, keeps run_id and item as sent and dedupes by id", async () => {
    const { calls, fetch } = script(
      json({ events: [sample[2], sample[0], sample[1]].map((e) => view(e as Event)) }),
      json({ events: sample.slice(0, 4).map((e) => view(e)) }), // overlaps: 0..2 repeat
    );
    const got: Event[] = [];
    const stop = client(fetch).subscribeEvents("w1", (e) => got.push(e));
    await settle(0);
    expect(got.map((e) => e.seq)).toEqual(sample.slice(0, 3).map((e) => e.seq));
    expect(got[0]).toEqual(view(sample[0] as Event));
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

  it("fills only v and world_id when they are absent, from the request's own world", async () => {
    const { fetch } = script(json({ events: [without(sample[0] as Event, "v", "world_id")] }));
    const got: Event[] = [];
    client(fetch).subscribeEvents("w1", (e) => got.push(e));
    await settle(0);
    expect(got[0]).toEqual(view(sample[0] as Event));
  });

  it("withholds a row with no run_id or no item key, stops, and reports an out-of-date server once", async () => {
    for (const bad of [
      without(sample[1] as Event, "run_id"),
      { ...view(sample[1] as Event), run_id: "" },
      without(sample[1] as Event, "item"),
      { ...view(sample[1] as Event), world_id: "w_other" },
    ]) {
      const { calls, fetch } = script(
        json({ events: [view(sample[0] as Event), bad, view(sample[2] as Event)] }),
        json({ events: [] }),
      );
      const got: number[] = [];
      const errors: Error[] = [];
      client(fetch).subscribeEvents(
        "w1",
        (e) => got.push(e.seq),
        (e) => errors.push(e),
      );
      await settle(5000);
      expect(got).toEqual([sample[0]?.seq]); // the complete row before it, nothing after it
      expect(errors).toHaveLength(1);
      expect(errors[0]).toMatchObject({
        message: "This server is out of date for live runs.",
        retryable: false,
      });
      expect(calls).toHaveLength(1);
    }
  });

  it("keeps an item the server sent as null (a null is the server's own statement)", async () => {
    const { fetch } = script(json({ events: [{ ...view(sample[0] as Event), item: null }] }));
    const got: Event[] = [];
    client(fetch).subscribeEvents("w1", (e) => got.push(e));
    await settle(0);
    expect(got[0]?.item).toBeNull();
  });

  it("keeps polling when the consumer throws", async () => {
    const { fetch } = script(
      json({ events: [view(sample[0] as Event)] }),
      json({ events: sample.slice(0, 2).map((e) => view(e)) }),
    );
    const got: number[] = [];
    client(fetch).subscribeEvents("w1", (e) => {
      got.push(e.seq);
      throw new Error("consumer bug");
    });
    await settle(1000);
    expect(got).toEqual(sample.slice(0, 2).map((e) => e.seq));
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
