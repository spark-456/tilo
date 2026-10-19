// BQ-CTX-TEAMWORLD (ADR-0040 decisions 6 and 10; FR-TEAM-04/05): the web's one write for a work item, through the
// API client to POST /v1/work-items. The body names a world only when the person chose the world; the reply is
// read strictly, and "added" is the server's own answer, never a guess.
import { describe, expect, it, vi } from "vitest";
import { HttpClient, TiloApiError } from "../../../api/http";
import { addWorkItem, newAttemptKey, planFailure } from "./workItems";

const W = "w_launch";
const reply = (body: unknown, status = 201) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const clientOf = (fetch: typeof globalThis.fetch) =>
  new HttpClient({ baseUrl: "https://api.test", fetch });
const record = (over: Record<string, unknown> = {}) => ({
  id: "wi_abc",
  title: "Book the venue",
  status: "open",
  owner: "u_asha",
  ...over,
});
const sent = (f: ReturnType<typeof vi.fn>) => {
  const call = f.mock.calls[0] as [string, RequestInit] | undefined;
  return {
    url: new URL(String(call?.[0])),
    method: call?.[1]?.method,
    body: JSON.parse(String(call?.[1]?.body)) as Record<string, unknown>,
    key: new Headers(call?.[1]?.headers).get("idempotency-key"),
  };
};

describe("BQ_CTX_TEAMWORLD adding a work item", () => {
  it("FR_TEAM_04 a personal item posts a manual source and no world_id", async () => {
    const fetch = vi.fn(async () => reply(record()));
    const added = await addWorkItem(clientOf(fetch), {
      title: " Book the venue ",
      dueText: "",
      worldId: null,
    });
    const s = sent(fetch);
    expect(s.method).toBe("POST");
    expect(s.url.pathname).toBe("/v1/work-items");
    expect(s.body).toEqual({ title: "Book the venue", source: { kind: "manual", ref: null } });
    expect(added).toEqual({ id: "wi_abc", title: "Book the venue", worldId: null });
  });

  it("FR_TEAM_04 a world item posts the world_id and the due phrase, and reads it back from the answer", async () => {
    const fetch = vi.fn(async () => reply(record({ world_id: W, due_text: "friday" })));
    const added = await addWorkItem(clientOf(fetch), {
      title: "Book the venue",
      dueText: " friday ",
      worldId: W,
    });
    expect(sent(fetch).body).toEqual({
      title: "Book the venue",
      due_text: "friday",
      source: { kind: "manual", ref: null },
      world_id: W,
    });
    expect(added.worldId).toBe(W);
  });

  it("FR_TEAM_04 a retry carries the same Idempotency-Key, so a created item is never created twice", async () => {
    const fetch = vi.fn(async () => reply(record()));
    const key = newAttemptKey();
    expect(key === null || /^[A-Za-z0-9_-]{1,64}$/.test(key)).toBe(true);
    await addWorkItem(clientOf(fetch), { title: "a", dueText: "", worldId: null }, "attempt-1");
    expect(sent(fetch).key).toBe("attempt-1");
  });

  it("FR_TEAM_04 an answer that is not the item asked for is unreadable, never 'added'", async () => {
    const bad: unknown[] = [
      {},
      record({ id: "" }),
      record({ title: 5 }),
      record({ status: "proposed" }),
      record({ world_id: "w_other" }), // another world than the one asked for
      "ok",
    ];
    for (const body of bad) {
      const fetch = vi.fn(async () => reply(body));
      await expect(
        addWorkItem(clientOf(fetch), { title: "t", dueText: "", worldId: W }),
      ).rejects.toBeInstanceOf(TiloApiError);
    }
    // a personal item whose answer names a world is not what was asked for either
    const named = vi.fn(async () => reply(record({ world_id: W })));
    await expect(
      addWorkItem(clientOf(named), { title: "t", dueText: "", worldId: null }),
    ).rejects.toBeInstanceOf(TiloApiError);
  });

  it("FR_TEAM_04 an unreadable answer to a write says the item may have been added", async () => {
    const fetch = vi.fn(async () => reply({}));
    const err = await addWorkItem(clientOf(fetch), {
      title: "t",
      dueText: "",
      worldId: null,
    }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(TiloApiError);
    expect(planFailure(err)).toMatchObject({ retry: true });
    expect(planFailure(err).words).toContain("may have been added");
  });
});

describe("BQ_CTX_TEAMWORLD what a failure says", () => {
  const fail = (status: number | null, refusal: string | null = null, retryable = false) =>
    new TiloApiError("raw words", status, retryable, true, null, false, refusal);

  it("FR_TEAM_04 401 says to sign in, 403 says whose worlds, 404 says the world is gone; none offers a retry", () => {
    expect(planFailure(fail(401))).toMatchObject({ retry: false });
    expect(planFailure(fail(401)).words).toContain("sign in");
    expect(planFailure(fail(403, "forbidden")).words).toContain("a world you own or one shared");
    expect(planFailure(fail(404, "not_found")).words).toContain("could not find that world");
    for (const s of [401, 403, 404]) expect(planFailure(fail(s)).retry).toBe(false);
  });

  it("FR_TEAM_04 a 422 names the refusal in words (no field list is carried) and asks for an edit, not a retry", () => {
    const body = planFailure(fail(422, "invalid_body"));
    expect(body.words).toContain("title or due date");
    expect(body.retry).toBe(false);
    expect(planFailure(fail(422, "invalid_record")).words).toContain("due date");
    expect(planFailure(fail(422, "invalid_body")).words).not.toContain("invalid_body");
  });

  it("FR_TEAM_04 an unreachable server or a 5xx says the item may not have been added and offers a retry", () => {
    for (const e of [fail(null, null, true), fail(500, null, true), fail(503, null, true)]) {
      const plan = planFailure(e);
      expect(plan.retry).toBe(true);
      expect(plan.words).toContain("may not have been added");
    }
  });

  it("FR_TEAM_04 a refusal word is never shown raw", () => {
    const plan = planFailure(fail(429, "rate_limited"));
    expect(plan.words).not.toContain("rate_limited");
    expect(plan.words).not.toContain("raw words");
  });
});
