// NFR-03 / NFR-22 (live defect 15 Oct 2026): POST /intake took 122.6 s, the web gave up at 120 s, and the owner saw a
// failure while the server finished and stored the plan unseen. The server now answers inside its deadline
// (config/intake.yaml, 503 `intake_deadline` when the time is gone). The web's half: a reply that is lost (timeout or a
// dropped connection) is asked for once more with the SAME Idempotency-Key, which makes the server hand back the plan
// it already made (or wait for it) instead of a dead end; a refusal the server did send is never retried here.
import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpClient, INTAKE_TIMEOUT_MS, TiloApiError } from "./http";

afterEach(() => {
  vi.useRealTimers();
});

const PLAN = {
  task_id: "t_1",
  brief: { goal: "Compare suppliers" },
  questions: [],
  files: [],
};
const ok = () =>
  new Response(JSON.stringify(PLAN), {
    status: 201,
    headers: { "content-type": "application/json" },
  });
const refused = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

function scripted(steps: Array<() => Response | Promise<Response>>) {
  const keys: string[] = [];
  const fetchFn = vi.fn(async (_url: string, init: RequestInit) => {
    keys.push(new Headers(init.headers).get("Idempotency-Key") ?? "");
    const step = steps[Math.min(keys.length, steps.length) - 1];
    if (!step) throw new Error("no step");
    return step();
  }) as unknown as typeof fetch;
  return { keys, fetchFn, client: new HttpClient({ baseUrl: "http://api.test", fetch: fetchFn }) };
}

const send = (c: HttpClient) => c.submitIntake("Compare three suppliers", []);

describe("NFR-03 the web recovers a lost intake reply instead of a dead end", () => {
  it("NFR_03_a_dropped_connection_is_asked_again_with_the_same_key_and_shows_the_plan", async () => {
    const { client, keys } = scripted([
      () => {
        throw new TypeError("network down");
      },
      ok,
    ]);

    const plan = await send(client);

    expect(plan.task_id).toBe("t_1");
    expect(keys).toHaveLength(2);
    expect(keys[1]).toBe(keys[0]);
  });

  it("NFR_03_a_timed_out_wait_is_asked_again_with_the_same_key_and_shows_the_plan", async () => {
    vi.useFakeTimers();
    const hang = (_url: string, init: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init.signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        );
      });
    const keys: string[] = [];
    let calls = 0;
    const fetchFn = ((url: string, init: RequestInit) => {
      keys.push(new Headers(init.headers).get("Idempotency-Key") ?? "");
      calls += 1;
      return calls === 1 ? hang(url, init) : Promise.resolve(ok());
    }) as unknown as typeof fetch;
    const client = new HttpClient({ baseUrl: "http://api.test", fetch: fetchFn });

    const pending = send(client);
    await vi.advanceTimersByTimeAsync(INTAKE_TIMEOUT_MS + 1);

    expect((await pending).task_id).toBe("t_1");
    expect(keys).toHaveLength(2);
    expect(keys[1]).toBe(keys[0]);
  });

  it("NFR_03_two_lost_replies_end_with_the_retry_message_and_keep_the_key_not_a_loop", async () => {
    const { client, keys } = scripted([
      () => {
        throw new TypeError("network down");
      },
    ]);

    await expect(send(client)).rejects.toMatchObject({ retryable: true, status: null });

    expect(keys).toHaveLength(2);
    await expect(send(client)).rejects.toBeInstanceOf(TiloApiError);
    expect(new Set(keys).size).toBe(1); // a manual retry is still the same intent
  });

  it("NFR_03_a_refusal_the_server_did_send_is_never_asked_again", async () => {
    const { client, keys } = scripted([
      () => refused(503, { detail: { code: "intake_deadline", message: "long text" } }),
    ]);

    await expect(send(client)).rejects.toMatchObject({ status: 503 });

    expect(keys).toHaveLength(1);
  });

  it("NFR_03_the_server_deadline_503_is_said_in_the_webs_own_words", async () => {
    const { client } = scripted([
      () =>
        refused(503, {
          detail: {
            code: "intake_deadline",
            message: "Making the plan took too long, so nothing was started. Try again.",
          },
        }),
    ]);

    const e = (await send(client).catch((x: unknown) => x)) as TiloApiError;

    expect(e.message).toMatch(/took too long/i);
    expect(e.message).toMatch(/nothing was started/i);
    expect(e.message).not.toMatch(/_/);
    expect(e.retryable).toBe(true);
    expect(e.code).toBe("intake_deadline");
    expect(e.replayOnly).toBe(false);
  });

  it("NFR_03_the_web_waits_longer_than_the_servers_deadline", () => {
    expect(INTAKE_TIMEOUT_MS).toBeGreaterThanOrEqual(90_000); // config/intake.yaml deadline_seconds + 10 s
    expect(INTAKE_TIMEOUT_MS).toBeLessThanOrEqual(110_000);
  });
});
