// NFR-22 (PRD 17.2): "Graceful degradation: model or quota failure offers labelled replays and a clear banner;
// channels queue and retry". This file is the web client's half of the wire: services/api (PR #566, BQ-NFR22-1)
// answers 503 {"detail", "replay_only": true, "code": "model_unavailable"} when every Director candidate failed on
// quota or availability, and NFR-24's replay-only refusal is 503 {"detail", "replay_only": true} (no code). Today
// HttpClient collapses every 5xx to "Tilo had a problem on its side." and drops both fields.
//
// Decisions (docs/open-questions.md BQ-NFR22-2..): the replay-only flag is `TiloApiError.replayOnly` (boolean, false
// unless the server said `replay_only: true` on a 503); the message is a fixed web sentence, never the server's text.
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { HttpClient, TiloApiError } from "./http";

/** The API's own texts (services/api deps.py), used verbatim so the test sees what the wire carries. */
const MODEL_UNAVAILABLE_DETAIL =
  "The model is unavailable right now (quota or outage), so nothing new was started; finished runs can still be replayed.";
const REPLAY_ONLY_DETAIL =
  "This link is replay-only right now: new work is paused; finished runs can still be replayed.";
const GENERIC_5XX = "Tilo had a problem on its side.";

function clientAnswering(status: number, body: unknown): HttpClient {
  const fetchFn = (async () =>
    new Response(typeof body === "string" ? body : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    })) as typeof fetch;
  return new HttpClient({ baseUrl: "http://api.test", fetch: fetchFn });
}

const intake = (c: HttpClient) => c.submitIntake("Prepare the weekly summary.", []);
const approaches = (c: HttpClient) => c.getApproaches("t1");

async function failureOf(call: Promise<unknown>): Promise<TiloApiError> {
  try {
    await call;
  } catch (error) {
    expect(error).toBeInstanceOf(TiloApiError);
    return error as TiloApiError;
  }
  throw new Error("the call should have failed");
}

type Flagged = TiloApiError & { replayOnly?: unknown };
const MODEL_UNAVAILABLE_BODY = {
  detail: MODEL_UNAVAILABLE_DETAIL,
  replay_only: true,
  code: "model_unavailable",
};

describe("NFR-22 http.ts keeps the replay-only label of a model failure", () => {
  it("NFR_22 intake: a 503 model_unavailable keeps its code and exposes replayOnly", async () => {
    const error = (await failureOf(
      intake(clientAnswering(503, MODEL_UNAVAILABLE_BODY)),
    )) as Flagged;
    expect(error.status).toBe(503);
    expect(error.code).toBe("model_unavailable");
    expect(error.replayOnly).toBe(true);
  });

  it("NFR_22 approaches: a 503 model_unavailable keeps its code and exposes replayOnly", async () => {
    const error = (await failureOf(
      approaches(clientAnswering(503, MODEL_UNAVAILABLE_BODY)),
    )) as Flagged;
    expect(error.status).toBe(503);
    expect(error.code).toBe("model_unavailable");
    expect(error.replayOnly).toBe(true);
  });

  it("NFR_22 the message says live models are unavailable and replays are offered, in a sentence of the web's own", async () => {
    for (const call of [intake, approaches]) {
      const error = await failureOf(call(clientAnswering(503, MODEL_UNAVAILABLE_BODY)));
      expect(error.message).toMatch(/live models are unavailable/i);
      expect(error.message).toMatch(/replay/i);
      expect(error.message).not.toBe(GENERIC_5XX);
      expect(error.message).not.toBe(MODEL_UNAVAILABLE_DETAIL); // never the server's text
    }
  });

  it("NFR_22 the server's free text is never echoed, whatever it says", async () => {
    const hostile = 'ZZ-SERVER-TEXT-7Q <script>alert(1)</script> {"code":"x"} AIza-not-a-key';
    const error = await failureOf(
      intake(clientAnswering(503, { ...MODEL_UNAVAILABLE_BODY, detail: hostile })),
    );
    expect(error.message).not.toContain("ZZ-SERVER-TEXT-7Q");
    expect(error.message).not.toMatch(/[<>{}]/);
    expect(error.message).toMatch(/live models are unavailable/i);
  });

  it("NFR_22 property: the sentence is the same for every server text (fixed, not derived)", async () => {
    const reference = (await failureOf(intake(clientAnswering(503, MODEL_UNAVAILABLE_BODY))))
      .message;
    await fc.assert(
      fc.asyncProperty(fc.string({ maxLength: 400 }), async (detail) => {
        const error = (await failureOf(
          intake(clientAnswering(503, { ...MODEL_UNAVAILABLE_BODY, detail })),
        )) as Flagged;
        expect(error.message).toBe(reference);
        expect(error.replayOnly).toBe(true);
      }),
      { numRuns: 25 },
    );
  });

  it("NFR_22 a model failure is not retryable at once: the server started nothing, so the offer is the next step", async () => {
    const error = await failureOf(intake(clientAnswering(503, MODEL_UNAVAILABLE_BODY)));
    expect(error.retryable).toBe(false);
    expect(error.write).toBe(true); // intake is a write call, as before
    const read = await failureOf(approaches(clientAnswering(503, MODEL_UNAVAILABLE_BODY)));
    expect(read.write).toBe(false);
  });
});

describe("NFR-22 / NFR-24 the replay-only refusal is labelled the same way", () => {
  it("NFR_24 a 503 replay_only refusal (no code) exposes replayOnly with the same sentence", async () => {
    const refusal = { detail: REPLAY_ONLY_DETAIL, replay_only: true };
    const labelled = await failureOf(intake(clientAnswering(503, MODEL_UNAVAILABLE_BODY)));
    for (const call of [intake, approaches]) {
      const error = (await failureOf(call(clientAnswering(503, refusal)))) as Flagged;
      expect(error.status).toBe(503);
      expect(error.replayOnly).toBe(true);
      expect(error.code).toBeNull(); // the server sent none; nothing is made up
      expect(error.message).toBe(labelled.message);
      expect(error.message).not.toContain("replay-only right now"); // not the server's text
    }
  });
});

describe("NFR-22 no regressions: other failures keep their copy", () => {
  it.each([
    [
      { detail: "The safety screen is unavailable; nothing was stored." },
      "The safety screen is unavailable. Try again later.",
    ],
    [
      { detail: "The safety screen is unavailable; nothing was answered." },
      "The safety screen is unavailable. Try again later.",
    ],
    [
      { detail: "The safety screen is unavailable; nothing changed." },
      "The safety screen is unavailable. Try again later.",
    ],
    [{ detail: "not_configured" }, "This feature is not configured on this server."],
    [
      { code: "not_configured", detail: "private server configuration" },
      "This feature is not configured on this server.",
    ],
    [{ detail: "The safety screen is unavailable; private traceback" }, GENERIC_5XX],
  ])("NFR_22 W1 maps known 503 %j to fixed web copy", async (body, message) => {
    const error = await failureOf(intake(clientAnswering(503, body)));
    expect(error.message).toBe(message);
    expect(error.replayOnly).toBe(false);
    expect(error.retryable).toBe(true);
  });

  it("NFR_22 other 5xx keep today's generic sentence and no replay label", async () => {
    for (const status of [500, 502, 503, 504]) {
      for (const call of [intake, approaches]) {
        const error = (await failureOf(
          call(clientAnswering(status, { detail: "upstream exploded" })),
        )) as Flagged;
        expect(error.message).toBe(GENERIC_5XX);
        expect(error.replayOnly).toBeFalsy();
        expect(error.retryable).toBe(true);
      }
    }
  });

  it("NFR_22 a 503 whose body is not JSON, or has no replay_only, is a generic 5xx", async () => {
    for (const body of [
      "Service Unavailable",
      {},
      { detail: "x" },
      { code: "model_unavailable" },
    ]) {
      const error = (await failureOf(intake(clientAnswering(503, body)))) as Flagged;
      expect(error.message).toBe(GENERIC_5XX);
      expect(error.replayOnly).toBeFalsy();
    }
  });

  it("NFR_22 only replay_only === true on a 503 labels a failure (not 'true', 1, or a 4xx)", async () => {
    for (const flag of ["true", 1, "yes", false, null]) {
      const error = (await failureOf(
        intake(clientAnswering(503, { ...MODEL_UNAVAILABLE_BODY, replay_only: flag })),
      )) as Flagged;
      expect(error.replayOnly).toBeFalsy();
      expect(error.message).toBe(GENERIC_5XX);
    }
    for (const status of [400, 403, 404, 409]) {
      const error = (await failureOf(
        intake(clientAnswering(status, MODEL_UNAVAILABLE_BODY)),
      )) as Flagged;
      expect(error.replayOnly).toBeFalsy();
      expect(error.message).not.toMatch(/live models are unavailable/i);
    }
  });

  it("NFR_22 SEC-15 refusals and a dropped connection are unchanged and unlabelled", async () => {
    const refused = (await failureOf(
      intake(clientAnswering(403, { detail: "Not open yet.", code: "under_construction" })),
    )) as Flagged;
    expect(refused.code).toBe("under_construction");
    expect(refused.message).toBe("Not open yet.");
    expect(refused.replayOnly).toBeFalsy();

    const offline = new HttpClient({
      baseUrl: "http://api.test",
      fetch: (async () => {
        throw new TypeError("fetch failed");
      }) as typeof fetch,
    });
    const dropped = (await failureOf(intake(offline))) as Flagged;
    expect(dropped.message).toBe("Tilo could not be reached. Check your connection and try again.");
    expect(dropped.replayOnly).toBeFalsy();
  });
});
