// SEC-16 lifetime cap and the feedback call, the HTTP client's half (user request, 8 Oct 2026; not in the PRD;
// services/api/tests/API_SPEND_FEEDBACK.md).
//
// 1. The API refuses new live work at a uid's LIFETIME cap with 403 {"detail", "code": "spend_cap_reached"}
//    (services/api/tests/API_SEC_16.md). The per-run and daily limits never use that code: the daily hard cap is the
//    NFR-24 replay-only 503 {"replay_only": true}; a run at its cap just runs that unit as replay. So the web can tell
//    them apart by one thing: `isLifetimeCap(error)`, exported from ./http, true only for a TiloApiError that is a 403
//    whose `code` is "spend_cap_reached". Anything else, including the other 403s of SEC-15, is false.
// 2. `HttpClient.submitFeedback(text)` (also on the `TiloClient` interface): POST {base}/v1/feedback with the JSON body
//    {"text", "context": "lifetime_cap"} and nothing else (the API takes the uid from the sign-in token, never the
//    body). It resolves only when the server confirmed (a 2xx whose JSON is {"received": true}); every other outcome
//    rejects with a TiloApiError, so no page can say "Thanks" for a request that did not land.
import { describe, expect, it } from "vitest";
import { CAP_BODY } from "../../test-support/lifetimeCap";
import { HttpClient, TiloApiError, isLifetimeCap } from "./http";

const BASE = "http://api.test";
const TOKEN = ["test", "id", "token"].join("."); // assembled at runtime: no secret in the file

interface Seen {
  url: string;
  init: RequestInit;
}

function clientAnswering(
  status: number,
  body: unknown,
  seen: Seen[] = [],
  raw?: string,
): HttpClient {
  const fetchFn = (async (url: string, init: RequestInit) => {
    seen.push({ url, init });
    return new Response(status === 204 ? null : (raw ?? JSON.stringify(body)), {
      status,
      headers: { "content-type": "application/json" },
    });
  }) as unknown as typeof fetch;
  return new HttpClient({ baseUrl: BASE, fetch: fetchFn, authToken: async () => TOKEN });
}
const failing = (): HttpClient =>
  new HttpClient({
    baseUrl: BASE,
    fetch: (async () => {
      throw new TypeError("Failed to fetch");
    }) as unknown as typeof fetch,
  });

async function rejection(call: Promise<unknown>): Promise<TiloApiError> {
  try {
    await call;
  } catch (error) {
    expect(error).toBeInstanceOf(TiloApiError);
    return error as TiloApiError;
  }
  throw new Error("the call should have been refused");
}

describe("SEC-16 isLifetimeCap: the one test the pop-up is keyed on", () => {
  it("SEC_16_FEEDBACK a 403 spend_cap_reached on intake is a lifetime cap, not retryable, with its code", async () => {
    const error = await rejection(
      clientAnswering(403, CAP_BODY).submitIntake("Prepare the summary.", []),
    );
    expect(error.status).toBe(403);
    expect(error.code).toBe("spend_cap_reached");
    expect(error.retryable).toBe(false);
    expect(isLifetimeCap(error)).toBe(true);
  });

  it("SEC_16_FEEDBACK the same refusal on GET approaches is a lifetime cap too", async () => {
    const error = await rejection(clientAnswering(403, CAP_BODY).getApproaches("t1"));
    expect(isLifetimeCap(error)).toBe(true);
  });

  it.each([
    ["under_construction", 403],
    ["declaration_required", 403],
    ["rate_limited", 429],
    ["feedback_limit_reached", 429],
    ["model_unavailable", 503],
  ])("SEC_16_FEEDBACK a %s refusal (%i) is not a lifetime cap", async (code, status) => {
    const error = await rejection(
      clientAnswering(status, { detail: "No.", code }).submitIntake("x", []),
    );
    expect(isLifetimeCap(error)).toBe(false);
  });

  it("SEC_16_FEEDBACK a 403 with no code (a role refusal) is not a lifetime cap", async () => {
    const error = await rejection(
      clientAnswering(403, { detail: "Forbidden" }).submitIntake("x", []),
    );
    expect(isLifetimeCap(error)).toBe(false);
  });

  it("SEC_16_FEEDBACK the daily replay-only 503 is not a lifetime cap", async () => {
    const error = await rejection(
      clientAnswering(503, {
        detail: "This link is replay-only right now: new work is paused.",
        replay_only: true,
      }).submitIntake("x", []),
    );
    expect(error.replayOnly).toBe(true);
    expect(isLifetimeCap(error)).toBe(false);
  });

  it("SEC_16_FEEDBACK the code only counts on a 403: the same code on a 409 or a 500 is not a lifetime cap", async () => {
    for (const status of [409, 422, 500]) {
      const error = await rejection(clientAnswering(status, CAP_BODY).submitIntake("x", []));
      expect(isLifetimeCap(error), String(status)).toBe(false);
    }
  });

  it("SEC_16_FEEDBACK anything that is not a TiloApiError is not a lifetime cap", () => {
    const lookalike = Object.assign(new Error("x"), { status: 403, code: "spend_cap_reached" });
    for (const value of [lookalike, null, undefined, "spend_cap_reached", 403, {}]) {
      expect(isLifetimeCap(value)).toBe(false);
    }
  });
});

describe("SEC-16 submitFeedback: one POST, confirmed or refused", () => {
  it("SEC_16_FEEDBACK it POSTs {text, context} as JSON to /v1/feedback with the sign-in token in the header only", async () => {
    const seen: Seen[] = [];
    await clientAnswering(201, { received: true }, seen).submitFeedback("I liked the plan view.");

    expect(seen).toHaveLength(1);
    expect(seen[0]?.url).toBe(`${BASE}/v1/feedback`);
    const init = seen[0]?.init as RequestInit;
    expect(init.method).toBe("POST");
    const headers = new Headers(init.headers);
    expect(headers.get("content-type")).toMatch(/^application\/json/);
    expect(headers.get("authorization")).toBe(`Bearer ${TOKEN}`);
    expect(JSON.parse(String(init.body))).toEqual({
      text: "I liked the plan view.",
      context: "lifetime_cap",
    });
    expect(seen[0]?.url).not.toContain(TOKEN);
    expect(String(init.body)).not.toContain(TOKEN);
  });

  it("SEC_16_FEEDBACK the body never carries a uid or any other field", async () => {
    const seen: Seen[] = [];
    await clientAnswering(201, { received: true }, seen).submitFeedback("x");
    expect(Object.keys(JSON.parse(String((seen[0]?.init as RequestInit).body))).sort()).toEqual([
      "context",
      "text",
    ]);
  });

  it("SEC_16_FEEDBACK it resolves with nothing on the server's {received: true}", async () => {
    await expect(
      clientAnswering(201, { received: true }).submitFeedback("x"),
    ).resolves.toBeUndefined();
  });

  it.each([
    ["a 200 with no confirmation", 200, {}],
    ["a 201 that says received false", 201, { received: false }],
    ["a 201 whose body is not JSON (a proxy page)", 201, undefined],
    ["a 204 with no body", 204, undefined],
  ])("SEC_16_FEEDBACK %s is not a confirmation: it rejects", async (_name, status, body) => {
    const raw = body === undefined ? "<html>captive portal</html>" : undefined;
    const error = await rejection(clientAnswering(status, body, [], raw).submitFeedback("x"));
    expect(error.write).toBe(true);
  });

  it.each([
    [401, { detail: "You need to sign in." }, null],
    [403, { detail: "Not open.", code: "under_construction" }, "under_construction"],
    [415, { detail: "Send application/json." }, null],
    [422, { detail: "Write a few words first." }, null],
    [429, { detail: "Too much feedback.", code: "rate_limited" }, "rate_limited"],
    [429, { detail: "That is all.", code: "feedback_limit_reached" }, "feedback_limit_reached"],
  ])(
    "SEC_16_FEEDBACK a %i refusal rejects as a TiloApiError, not retryable, code %s",
    async (status, body, code) => {
      const error = await rejection(clientAnswering(status, body).submitFeedback("x"));
      expect(error.status).toBe(status);
      expect(error.code).toBe(code);
      expect(error.retryable).toBe(false);
      expect(error.write).toBe(true);
    },
  );

  it("SEC_16_FEEDBACK a 5xx rejects as retryable", async () => {
    const error = await rejection(clientAnswering(500, { detail: "boom" }).submitFeedback("x"));
    expect(error.status).toBe(500);
    expect(error.retryable).toBe(true);
    expect(error.write).toBe(true);
  });

  it("SEC_16_FEEDBACK a 503 not_configured (the store is not wired yet) rejects", async () => {
    const error = await rejection(
      clientAnswering(503, { detail: "not_configured" }).submitFeedback("x"),
    );
    expect(error.status).toBe(503);
  });

  it("SEC_16_FEEDBACK a network failure rejects as retryable and says nothing of the host", async () => {
    const error = await rejection(failing().submitFeedback("x"));
    expect(error.status).toBeNull();
    expect(error.retryable).toBe(true);
    expect(error.write).toBe(true);
    expect(error.message).not.toMatch(/api\.test|Failed to fetch/);
  });

  it("SEC_16_FEEDBACK the client does not retry a failed feedback call on its own", async () => {
    const seen: Seen[] = [];
    await rejection(clientAnswering(500, { detail: "boom" }, seen).submitFeedback("x"));
    expect(seen).toHaveLength(1);
  });
});
