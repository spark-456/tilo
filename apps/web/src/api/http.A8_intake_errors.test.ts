// A8 / NFR-22 (14 Oct): what a person reads when POST /intake is refused or does not answer. The server's wire
// shapes are services/api/src/tilo_api/intake.py (503 {detail} per cause, 429 demo_runs_busy, 409 committed).
// Codes are never shown as they are; a 503 that stored nothing gets a sentence of ours; a reply that never comes
// ends after INTAKE_TIMEOUT_MS with a plain message that keeps the idempotency key (a retry is the same intent).
import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpClient, INTAKE_TIMEOUT_MS, type TiloApiError } from "./http";

afterEach(() => {
  vi.useRealTimers();
});

function answering(status: number, body: unknown): HttpClient {
  const fetchFn = (async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    })) as typeof fetch;
  return new HttpClient({ baseUrl: "http://api.test", fetch: fetchFn });
}

async function failure(call: Promise<unknown>): Promise<TiloApiError> {
  try {
    await call;
  } catch (e) {
    return e as TiloApiError;
  }
  throw new Error("expected a failure");
}

const send = (c: HttpClient) => c.submitIntake("Compare three suppliers", []);

describe("A8_intake_errors: sentences, not codes", () => {
  it.each([
    [
      "the safety screen",
      { detail: "The safety screen is unavailable; nothing was stored." },
      /safety check/i,
    ],
    [
      "task screening",
      { detail: "Task screening is unavailable; nothing was stored." },
      /screen this task/i,
    ],
    ["upload storage", { detail: "Upload storage is unavailable; retry." }, /attached files/i],
    ["not_configured", { detail: "not_configured" }, /not set up/i],
  ])("A8_intake_503_%s becomes one retryable sentence of ours", async (_n, body, says) => {
    const e = await failure(send(answering(503, body)));
    expect(e.status).toBe(503);
    expect(e.retryable).toBe(true);
    expect(e.message).toMatch(says);
    expect(e.message).not.toContain("nothing was stored");
  });

  it("A8_intake_503_with_an_unknown_detail_keeps_the_generic_server_trouble_sentence", async () => {
    const e = await failure(send(answering(503, { detail: "store_unavailable" })));
    expect(e.message).toBe("Tilo had a problem on its side.");
  });

  it.each([
    [429, { detail: "demo_runs_busy" }, /busy/i],
    [402, { detail: "cap_reached" }, /limit/i],
  ])(
    "A8_intake_%s_with_a_code_shows_a_plain_sentence_never_the_code",
    async (status, body, says) => {
      const e = await failure(send(answering(status, body)));
      expect(e.status).toBe(status);
      expect(e.message).toMatch(says);
      expect(e.message).not.toMatch(/_/);
    },
  );

  it("A8_intake_a_short_server_sentence_is_still_shown", async () => {
    const e = await failure(
      send(answering(422, { error: "The task text is over the 4,000 character limit." })),
    );
    expect(e.message).toBe("The task text is over the 4,000 character limit.");
  });
});

describe("A8_intake_timeout: a reply that never comes ends", () => {
  it("A8_intake_ends_after_the_timeout_with_a_retryable_plain_message_and_keeps_the_key", async () => {
    vi.useFakeTimers();
    const keys: string[] = [];
    const fetchFn = ((_url: string, init: RequestInit) => {
      keys.push(new Headers(init.headers).get("Idempotency-Key") ?? "");
      return new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        );
      });
    }) as unknown as typeof fetch;
    const client = new HttpClient({ baseUrl: "http://api.test", fetch: fetchFn });
    const pending = failure(send(client));
    await vi.advanceTimersByTimeAsync(INTAKE_TIMEOUT_MS + 1);
    const e = await pending;
    expect(e.message).toMatch(/taking too long/i);
    expect(e.retryable).toBe(true);
    expect(e.status).toBeNull();
    // a manual retry of the same text is the same intent: the same Idempotency-Key goes out again
    const again = failure(send(client));
    await vi.advanceTimersByTimeAsync(INTAKE_TIMEOUT_MS + 1);
    await again;
    expect(keys).toHaveLength(2);
    expect(keys[1]).toBe(keys[0]);
  });
});
