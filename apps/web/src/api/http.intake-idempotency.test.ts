import { describe, expect, it, vi } from "vitest";
import { describeError } from "./describeError";
import { HttpClient } from "./http";

const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const accepted = () => reply({ task_id: "t1", brief: {}, questions: [], files: [] });
const committed = () =>
  reply(
    {
      detail: {
        code: "intake_already_committed",
        task_id: "private-task",
        world_id: "private-world",
      },
    },
    409,
  );

function setup(...responses: Array<Response | Error>) {
  const fetch = vi.fn(async (_url: unknown, _init?: RequestInit) => {
    const next = responses.shift();
    if (!next) throw new Error("Unexpected POST");
    if (next instanceof Error) throw next;
    return next;
  });
  const client = new HttpClient({
    baseUrl: "https://api.test",
    fetch: fetch as typeof globalThis.fetch,
    authToken: async () => "test.token",
    appCheckToken: async () => "test.appcheck",
  });
  const headers = (index: number) => new Headers(fetch.mock.calls[index]?.[1]?.headers);
  const key = (index: number) => headers(index).get("Idempotency-Key");
  return { client, fetch, headers, key };
}

describe("FR-INT-01 intake idempotency follow-up", () => {
  it("QA-11 shares an in-flight intake and releases it after success", async () => {
    let resolve!: (value: Response) => void;
    const pending = new Promise<Response>((done) => {
      resolve = done;
    });
    const fetch = vi.fn(() => pending);
    const client = new HttpClient({ baseUrl: "https://api.test", fetch });
    const first = client.submitIntake("Task", []);
    const duplicate = client.submitIntake("Task", []);
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    resolve(accepted());
    expect(await duplicate).toEqual(await first);
    fetch.mockImplementationOnce(async () => accepted());
    await client.submitIntake("Task", []);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("keeps the opaque key after network, server and unreadable reply failures with unchanged File references", async () => {
    const s = setup(new Error("offline"), reply({}, 503), new Response("broken"), accepted());
    const file = new File(["source"], "source.txt");
    for (let i = 0; i < 3; i++) {
      await expect(s.client.submitIntake("Task", [file])).rejects.toMatchObject({
        retryable: true,
      });
    }
    await s.client.submitIntake("Task", [file]);
    expect(s.key(0)).toMatch(/^[a-f0-9-]{36}$/);
    expect([s.key(1), s.key(2), s.key(3)]).toEqual([s.key(0), s.key(0), s.key(0)]);
    expect(s.headers(3).get("Authorization")).toBe("Bearer test.token");
    expect(s.headers(3).get("X-Firebase-AppCheck")).toBe("test.appcheck");
    expect(s.headers(3).has("content-type")).toBe(false);
    expect(s.fetch.mock.calls[3]?.[1]?.body).toBeInstanceOf(FormData);
    expect(s.fetch).toHaveBeenCalledTimes(4);
  });

  it("starts a new key for changed text, file identity, file order or Quick/Thinking mode", async () => {
    const s = setup(...Array.from({ length: 6 }, () => new Error("offline")));
    const a = new File(["a"], "same.txt");
    const b = new File(["b"], "same.txt");
    await s.client.submitIntake("One", [a, b]).catch(() => undefined);
    await s.client.submitIntake("Two", [a, b]).catch(() => undefined);
    await s.client.submitIntake("Two", [b, a]).catch(() => undefined);
    await s.client.submitIntake("Two", [b, new File(["a"], "same.txt")]).catch(() => undefined);
    await s.client.submitIntake("Two", [b, a], "quick").catch(() => undefined);
    await s.client.submitIntake("Two", [b, a]).catch(() => undefined);
    expect(new Set(Array.from({ length: 6 }, (_, i) => s.key(i))).size).toBe(6);
  });

  it("starts a fresh key after success or a definite refusal", async () => {
    const s = setup(accepted(), reply({ detail: "Too long" }, 422), accepted());
    await s.client.submitIntake("Task", []);
    await expect(s.client.submitIntake("Task", [])).rejects.toMatchObject({ retryable: false });
    await s.client.submitIntake("Task", []);
    expect(new Set([s.key(0), s.key(1), s.key(2)]).size).toBe(3);
  });

  it("reuses Quick keys until a readable answer, then creates a fresh intent", async () => {
    const answer = () => reply({ mode: "quick", outcome: "answered", text: "Answer" });
    const s = setup(reply({ mode: "quick" }), answer(), answer());
    await expect(s.client.submitIntake("Question", [], "quick")).rejects.toMatchObject({
      retryable: true,
    });
    await s.client.submitIntake("Question", [], "quick");
    await s.client.submitIntake("Question", [], "quick");
    expect(s.key(1)).toBe(s.key(0));
    expect(s.key(2)).not.toBe(s.key(1));
    expect((s.fetch.mock.calls[1]?.[1]?.body as FormData).get("mode")).toBe("quick");
  });

  it("shows a fixed non-retryable already-committed message without ids or another POST", async () => {
    const s = setup(committed());
    await expect(s.client.submitIntake("Task", [])).rejects.toMatchObject({
      message: "This task was already submitted. Check your worlds before starting another task.",
      code: "intake_already_committed",
      status: 409,
      retryable: false,
      write: true,
    });
    expect(s.fetch).toHaveBeenCalledTimes(1);
  });

  it("shows already-committed through the page formatter without claiming nothing changed or suggesting a retry", async () => {
    const s = setup(committed());
    const error = await s.client.submitIntake("Task", []).catch((error: unknown) => error);
    expect(describeError("start the task", error)).toBe(
      "This task was already submitted. Check your worlds before starting another task.",
    );
  });

  it("does not treat unrelated 409s or another route's nested detail as an intake commit", async () => {
    const s = setup(
      reply({ detail: { code: "other", task_id: "private-task" } }, 409),
      committed(),
    );
    await expect(s.client.submitIntake("Task", [])).rejects.toMatchObject({
      message: "That cannot be done right now.",
      code: null,
    });
    await expect(s.client.postJson("/other", {})).rejects.toMatchObject({
      message: "That cannot be done right now.",
      code: null,
    });
  });
});
