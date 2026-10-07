// SEC-10 (PRD 16, "Rate limits, App Check and spend caps"; PRD 6.2 row "Firebase Authentication, App Check"):
// every call the web api client makes carries the App Check token in the `X-Firebase-AppCheck` header, so the
// API can tell its own web app from a script. The client takes the token from an injected getter
// (`HttpClientOptions.appCheckToken`, a `() => Promise<string | null>`), which `appcheck/appCheck.ts` builds
// (see appCheck.SEC-10.test.ts). A getter that fails or answers null never breaks the call: the call goes out
// with no header (the API only logs a missing token until enforcement is switched on).
//
// No network: the client is given a fake `fetch`. The token below is a fake, assembled at runtime.
import { afterEach, describe, expect, it, vi } from "vitest";
import { chooseClient } from "./config";
import { FixtureClient } from "./fixtureClient";
import { HttpClient } from "./http";

const HEADER = "x-firebase-appcheck"; // header names are case-insensitive; compared through `Headers`
const fakeToken = (n: number | string = 1) => ["fake", "app", "check", String(n)].join(".");

interface Seen {
  readonly url: string;
  readonly headers: Headers;
  readonly method: string;
}

/** A fake fetch that records each request and answers every path with a small JSON body. */
function recordingFetch(): { fetchFn: typeof fetch; seen: Seen[] } {
  const seen: Seen[] = [];
  const fetchFn = (async (input: RequestInfo | URL, init?: RequestInit) => {
    seen.push({
      url: String(input),
      headers: new Headers(init?.headers),
      method: init?.method ?? "GET",
    });
    return new Response(JSON.stringify({ events: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
  return { fetchFn, seen };
}

/** Runs one call to its end or its failure: a fake reply need not have the shape the call expects. */
const settle = (p: Promise<unknown>) => p.then(undefined, () => undefined);

/** Every public way the client reaches the API, one per route family. */
async function useEveryCall(client: HttpClient): Promise<void> {
  await settle(client.submitIntake("Prepare the weekly summary.", []));
  await settle(client.answerQuestions("t_1", [], {}));
  await settle(client.getApproaches("t_1"));
  await settle(client.approve("t_1", { approach_id: "a_1", budget_cap: 10 }));
  await settle(client.listCards("w_1"));
  await settle(client.answerCard("c_1", { option_id: "o_1" })); // refused before any request: not listed
  await settle(client.getDelivery("w_1"));
  await settle(client.getJson("/worlds"));
  await settle(client.stopAutopilot("w_1"));
  await settle(client.pauseWorld("w_1"));
  const stop = new AbortController();
  const layout = settle(client.getLayout("w_2", stop.signal)); // polls the world's events first
  const unsubscribe = client.subscribeEvents("w_3", () => undefined);
  await new Promise((resolve) => setTimeout(resolve, 60));
  unsubscribe();
  stop.abort();
  await layout;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("SEC-10 the web api client attaches the App Check token", () => {
  it("SEC-10 every request the client makes carries X-Firebase-AppCheck with the getter's token", async () => {
    const { fetchFn, seen } = recordingFetch();
    const token = fakeToken();
    const client = new HttpClient({
      baseUrl: "http://api.test",
      fetch: fetchFn,
      pollMs: 5,
      appCheckToken: async () => token,
    });
    await useEveryCall(client);

    // Intake, answers, approaches, approve, cards, delivery, getJson, stop, pause, layout's event poll and a
    // subscription's polls: at least these many requests went out, and not one of them is without the header.
    expect(seen.length).toBeGreaterThanOrEqual(10);
    const withoutHeader = seen.filter((r) => r.headers.get(HEADER) !== token);
    expect(withoutHeader.map((r) => `${r.method} ${r.url}`)).toEqual([]);
  });

  it("SEC-10 the header goes to the configured API origin only and does not disturb the body headers", async () => {
    const { fetchFn, seen } = recordingFetch();
    const client = new HttpClient({
      baseUrl: "http://api.test",
      fetch: fetchFn,
      appCheckToken: async () => fakeToken(),
    });
    await settle(client.submitIntake("Prepare the weekly summary.", []));
    await settle(client.approve("t_1", { approach_id: "a_1", budget_cap: 10 }));

    expect(seen.map((r) => new URL(r.url).origin)).toEqual(["http://api.test", "http://api.test"]);
    const [intake, approve] = seen;
    // The multipart intake body sets its own boundary: the client must not set a content-type for it.
    expect(intake?.headers.has("content-type")).toBe(false);
    expect(approve?.headers.get("content-type")).toBe("application/json");
  });

  it("SEC-10 the getter is asked for each request, so a refreshed token is used on the next call", async () => {
    const { fetchFn, seen } = recordingFetch();
    let n = 0;
    const getter = vi.fn(async () => fakeToken(++n));
    const client = new HttpClient({
      baseUrl: "http://api.test",
      fetch: fetchFn,
      appCheckToken: getter,
    });
    await settle(client.getDelivery("w_1"));
    await settle(client.getDelivery("w_1"));

    expect(seen.map((r) => r.headers.get(HEADER))).toEqual([fakeToken(1), fakeToken(2)]);
    expect(getter).toHaveBeenCalledTimes(2);
  });

  it("SEC-10 a getter that rejects does not break the call: it goes out with no header", async () => {
    const { fetchFn, seen } = recordingFetch();
    const client = new HttpClient({
      baseUrl: "http://api.test",
      fetch: fetchFn,
      appCheckToken: async () => {
        throw new Error("reCAPTCHA could not be reached");
      },
    });
    const result = await client.getJson("/worlds");

    expect(result).toEqual({ events: [] }); // the reply came back as it would without App Check
    expect(seen).toHaveLength(1);
    expect(seen[0]?.headers.has(HEADER)).toBe(false);
  });

  it("SEC-10 a getter that throws synchronously does not break the call either", async () => {
    const { fetchFn, seen } = recordingFetch();
    const client = new HttpClient({
      baseUrl: "http://api.test",
      fetch: fetchFn,
      appCheckToken: (() => {
        throw new Error("no sdk");
      }) as () => Promise<string | null>,
    });
    await expect(client.getJson("/worlds")).resolves.toEqual({ events: [] });
    expect(seen[0]?.headers.has(HEADER)).toBe(false);
  });

  it("SEC-10 a null or empty token sends no header (never an empty one)", async () => {
    for (const value of [null, ""]) {
      const { fetchFn, seen } = recordingFetch();
      const client = new HttpClient({
        baseUrl: "http://api.test",
        fetch: fetchFn,
        appCheckToken: async () => value,
      });
      await client.getJson("/worlds");
      expect(seen).toHaveLength(1);
      expect(seen[0]?.headers.has(HEADER)).toBe(false);
    }
  });

  it("SEC-10 with no getter configured the client sends no App Check header (fixture and local use)", async () => {
    const { fetchFn, seen } = recordingFetch();
    const client = new HttpClient({ baseUrl: "http://api.test", fetch: fetchFn });
    await client.getJson("/worlds");
    expect(seen).toHaveLength(1);
    expect(seen[0]?.headers.has(HEADER)).toBe(false);
  });

  it("SEC-10 the token is never written to the console", async () => {
    const { fetchFn } = recordingFetch();
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation(() => undefined),
    );
    const token = fakeToken("secretish");
    const failing = new HttpClient({
      baseUrl: "http://api.test",
      fetch: (async () => new Response("no", { status: 500 })) as typeof fetch,
      appCheckToken: async () => token,
    });
    await settle(failing.getDelivery("w_1"));
    const ok = new HttpClient({
      baseUrl: "http://api.test",
      fetch: fetchFn,
      appCheckToken: async () => token,
    });
    await settle(ok.getDelivery("w_1"));
    for (const spy of spies) expect(JSON.stringify(spy.mock.calls)).not.toContain(token);
  });

  it("SEC-10 a failed call's error text does not carry the token", async () => {
    const token = fakeToken("leak-check");
    const client = new HttpClient({
      baseUrl: "http://api.test",
      fetch: (async () =>
        new Response(JSON.stringify({ detail: "No." }), { status: 403 })) as typeof fetch,
      appCheckToken: async () => token,
    });
    const error = await client.getDelivery("w_1").then(
      () => null,
      (e: unknown) => e as Error,
    );
    expect(error).not.toBeNull();
    expect(String(error?.message)).not.toContain(token);
  });
});

describe("SEC-10 chooseClient passes the getter to the HTTP client only", () => {
  it("SEC-10 chooseClient with an API origin and a getter builds an HttpClient that sends the header", async () => {
    const { fetchFn, seen } = recordingFetch();
    vi.stubGlobal("fetch", fetchFn);
    const token = fakeToken();
    const client = chooseClient({
      apiUrl: "http://api.test",
      search: "",
      appCheckToken: async () => token,
    });
    expect(client).toBeInstanceOf(HttpClient);
    await settle((client as HttpClient).getJson("/worlds"));
    expect(seen).toHaveLength(1);
    expect(seen[0]?.headers.get(HEADER)).toBe(token);
  });

  it("SEC-10 chooseClient with no API origin stays the fixture client and never asks for a token", async () => {
    const fetchSpy = vi.fn(async () => {
      throw new Error("SEC-10: no backend in fixture mode");
    });
    vi.stubGlobal("fetch", fetchSpy);
    const getter = vi.fn(async () => fakeToken());
    for (const apiUrl of [undefined, "", "   "]) {
      const client = chooseClient({ apiUrl, search: "?speed=64", appCheckToken: getter });
      expect(client).toBeInstanceOf(FixtureClient);
      const intake = await client.submitIntake("fixture check", []);
      await client.getApproaches(intake.task_id);
    }
    expect(getter).not.toHaveBeenCalled(); // no reCAPTCHA, no Google, no API in the replay world
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
