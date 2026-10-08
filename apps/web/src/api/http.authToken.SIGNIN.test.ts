// SEC-15 / SIGNIN (PRD 6 platform row "Firebase Authentication"; PRD supplement SEC-15): the Firebase ID token goes on
// every call the web api client makes, as `Authorization: Bearer <token>`, beside `X-Firebase-AppCheck` (SEC-10).
//
// Public interface pinned here (all additive, mirroring SEC-10's `appCheckToken`):
//   HttpClientOptions.authToken?: () => Promise<string | null>     (apps/web/src/api/http.ts)
//   ClientConfig.authToken (chooseClient, src/api/config.ts); LiveApiOptions.authToken (createLiveApi, park/api/liveApi.ts)
//   parkApi(env, appCheckToken?, authToken?)                       (park/api/select.ts)
//   `authToken` exported from src/api/ClientProvider.tsx and handed on by park/app/context.tsx, like `appCheckToken`.
// - Asked before every request (the SDK caches and refreshes it); a getter that rejects, throws or answers null, or a token
//   that cannot be a header value, sends the request with no Authorization header and never turns it into "could not be
//   reached" (the API answers 401 and the page shows the sign-in).
// - The token goes in the header only: never in the URL, never in a body, never in an error message or the console;
//   credentials are never "include" (no cookies).
// - On a phone-width window the request also carries `X-Tilo-Channel: mobile_web` (BQ-SIGNIN-3), else no such header.
// - Fixture mode makes no request and never asks the getter.
// No network: a fake fetch. Tokens are fake and assembled at runtime.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import fc from "fast-check";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createLiveApi } from "../park/api/liveApi";
import { parkApi } from "../park/api/select";
import { chooseClient } from "./config";
import { FixtureClient } from "./fixtureClient";
import { HttpClient } from "./http";

const AUTH = "authorization";
const APP_CHECK = "x-firebase-appcheck";
const CHANNEL = "x-tilo-channel";
const BASE = "http://api.test";
const jwtish = (n: number | string = 1) => ["fake", "id", "token", String(n)].join(".");
const settle = (p: Promise<unknown>) => p.then(undefined, () => undefined);

interface Seen {
  readonly url: string;
  readonly method: string;
  readonly headers: Headers;
  readonly credentials: RequestCredentials | undefined;
  readonly body: unknown;
}

function recordingFetch(status = 200): { fetchFn: typeof fetch; seen: Seen[] } {
  const seen: Seen[] = [];
  const fetchFn = (async (input: RequestInfo | URL, init?: RequestInit) => {
    seen.push({
      url: String(input),
      method: init?.method ?? "GET",
      headers: new Headers(init?.headers),
      credentials: init?.credentials,
      body: init?.body,
    });
    return new Response(
      JSON.stringify(status === 200 ? { events: [] } : { detail: "Sign in to use this." }),
      {
        status,
        headers: { "content-type": "application/json" },
      },
    );
  }) as typeof fetch;
  return { fetchFn, seen };
}

async function useEveryCall(client: HttpClient): Promise<void> {
  await settle(client.submitIntake("Prepare the weekly summary.", []));
  await settle(client.answerQuestions("t_1", [], {}));
  await settle(client.getApproaches("t_1"));
  await settle(client.approve("t_1", { approach_id: "a_1", budget_cap: 10 }));
  await settle(client.listCards("w_1"));
  await settle(client.getDelivery("w_1"));
  await settle(client.getJson("/worlds"));
  await settle(client.postJson("/access/declaration", { declaration: "judge" }));
  await settle(client.stopAutopilot("w_1"));
  await settle(client.pauseWorld("w_1"));
  const stop = new AbortController();
  const layout = settle(client.getLayout("w_2", stop.signal));
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

describe("SEC-15 SIGNIN the web api client sends the Firebase ID token as a Bearer header", () => {
  it("SEC-15 SIGNIN every request carries Authorization: Bearer <token> and, beside it, the App Check token", async () => {
    const { fetchFn, seen } = recordingFetch();
    const token = jwtish();
    const client = new HttpClient({
      baseUrl: BASE,
      fetch: fetchFn,
      pollMs: 5,
      authToken: async () => token,
      appCheckToken: async () => "fake.app.check.token",
    });
    await useEveryCall(client);

    expect(seen.length).toBeGreaterThanOrEqual(10);
    expect(
      seen
        .filter((r) => r.headers.get(AUTH) !== `Bearer ${token}`)
        .map((r) => `${r.method} ${r.url}`),
    ).toEqual([]);
    expect(seen.filter((r) => r.headers.get(APP_CHECK) !== "fake.app.check.token")).toEqual([]);
  });

  it("SEC-15 SIGNIN the token is in the header only: not in any URL, any body, and credentials are never included", async () => {
    const { fetchFn, seen } = recordingFetch();
    const token = jwtish("secretmarker");
    const client = new HttpClient({
      baseUrl: BASE,
      fetch: fetchFn,
      pollMs: 5,
      authToken: async () => token,
    });
    await useEveryCall(client);

    expect(seen.length).toBeGreaterThanOrEqual(10);
    for (const r of seen) {
      expect(r.url, r.url).not.toContain("secretmarker");
      expect(new URL(r.url).origin).toBe(BASE);
      expect(typeof r.body === "string" ? r.body : "").not.toContain("secretmarker");
      expect(
        r.credentials === undefined || r.credentials === "omit" || r.credentials === "same-origin",
      ).toBe(true);
    }
  });

  it("SEC-15 SIGNIN the getter is asked for each request, so a refreshed token is used on the next call", async () => {
    const { fetchFn, seen } = recordingFetch();
    let n = 0;
    const getter = vi.fn(async () => jwtish(++n));
    const client = new HttpClient({ baseUrl: BASE, fetch: fetchFn, authToken: getter });
    await settle(client.getDelivery("w_1"));
    await settle(client.getDelivery("w_1"));
    expect(seen.map((r) => r.headers.get(AUTH))).toEqual([
      `Bearer ${jwtish(1)}`,
      `Bearer ${jwtish(2)}`,
    ]);
    expect(getter).toHaveBeenCalledTimes(2);
  });

  it("SEC-15 SIGNIN a long but real-sized Firebase token (about 3 KB of base64url) is sent", async () => {
    const { fetchFn, seen } = recordingFetch();
    const long = ["a".repeat(900), "b".repeat(1800), "c".repeat(342)].join(".");
    await new HttpClient({ baseUrl: BASE, fetch: fetchFn, authToken: async () => long }).getJson(
      "/worlds",
    );
    expect(seen[0]?.headers.get(AUTH)).toBe(`Bearer ${long}`);
  });

  it("SEC-15 SIGNIN no token (signed out, a local host, no config): no Authorization header, the call still goes out", async () => {
    const { fetchFn, seen } = recordingFetch();
    for (const getter of [async () => null, undefined]) {
      const client = new HttpClient({
        baseUrl: BASE,
        fetch: fetchFn,
        ...(getter ? { authToken: getter } : {}),
      });
      await expect(client.getJson("/worlds")).resolves.toEqual({ events: [] });
    }
    expect(seen).toHaveLength(2);
    expect(seen.filter((r) => r.headers.has(AUTH))).toEqual([]);
  });

  it("SEC-15 SIGNIN a getter that rejects, or throws synchronously, does not break the call: no header", async () => {
    const { fetchFn, seen } = recordingFetch();
    const rejects = new HttpClient({
      baseUrl: BASE,
      fetch: fetchFn,
      authToken: async () => {
        throw new Error("auth/network-request-failed");
      },
    });
    const throws = new HttpClient({
      baseUrl: BASE,
      fetch: fetchFn,
      authToken: (() => {
        throw new Error("sync failure");
      }) as unknown as () => Promise<string | null>,
    });
    await expect(rejects.getJson("/worlds")).resolves.toEqual({ events: [] });
    await expect(throws.getJson("/worlds")).resolves.toEqual({ events: [] });
    expect(seen).toHaveLength(2);
    expect(seen.filter((r) => r.headers.has(AUTH))).toEqual([]);
  });

  it("SEC-15 SIGNIN a token that cannot be a header value is not sent and does not make the call 'unreachable'", async () => {
    for (const bad of [
      "abc\r\nX-Evil: 1",
      "has space",
      "café.token.x",
      "tab\there",
      "nul\u0000byte",
      "a".repeat(20_000),
      "",
      "Bearer x.y.z",
    ]) {
      const { fetchFn, seen } = recordingFetch();
      const client = new HttpClient({ baseUrl: BASE, fetch: fetchFn, authToken: async () => bad });
      await expect(client.getJson("/worlds"), JSON.stringify(bad.slice(0, 20))).resolves.toEqual({
        events: [],
      });
      expect(seen).toHaveLength(1);
      expect(seen[0]?.headers.has(AUTH), JSON.stringify(bad.slice(0, 20))).toBe(false);
    }
  });

  it("SEC-15 SIGNIN a 401 reads as 'sign in' and the error carries neither the token nor the header", async () => {
    const { fetchFn } = recordingFetch(401);
    const token = jwtish("secretmarker");
    const client = new HttpClient({ baseUrl: BASE, fetch: fetchFn, authToken: async () => token });
    const error = await client.getJson("/worlds").then(
      () => null,
      (e: unknown) => e as Error & { status: number | null },
    );
    expect(error?.status).toBe(401);
    expect(JSON.stringify([error?.message, error?.name, Object.values(error ?? {})])).not.toContain(
      "secretmarker",
    );
  });

  it("SEC-15 SIGNIN a failing network does not put the token in the error or the console", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation(() => undefined),
    );
    const token = jwtish("secretmarker");
    const client = new HttpClient({
      baseUrl: BASE,
      fetch: (async () => {
        throw new TypeError(`Failed to fetch ${BASE} Authorization: Bearer ${token}`);
      }) as typeof fetch,
      authToken: async () => token,
    });
    const error = await client.getJson("/worlds").then(
      () => null,
      (e: unknown) => e as Error,
    );
    expect(error?.message ?? "").not.toContain("secretmarker");
    expect(JSON.stringify(spies.flatMap((s) => s.mock.calls))).not.toContain("secretmarker");
  });

  it("SEC-15 SIGNIN property: any token string is either sent exactly as a Bearer header or not sent, and the call succeeds", async () => {
    await fc.assert(
      fc.asyncProperty(fc.string({ maxLength: 200 }), async (token) => {
        const { fetchFn, seen } = recordingFetch();
        const client = new HttpClient({
          baseUrl: BASE,
          fetch: fetchFn,
          authToken: async () => token,
        });
        await expect(client.getJson("/worlds")).resolves.toEqual({ events: [] });
        const sent = seen[0]?.headers.get(AUTH);
        expect(sent === null || sent === `Bearer ${token}`).toBe(true);
        if (/[^A-Za-z0-9._~+/=-]/.test(token) || token === "") expect(sent).toBeNull();
      }),
      { numRuns: 80 },
    );
  });
});

describe("SEC-15 SIGNIN the channel hint", () => {
  const phone = (matches: boolean) => vi.stubGlobal("window", { matchMedia: () => ({ matches }) });

  it("SEC-15 SIGNIN on a phone-width window the request says mobile_web", async () => {
    phone(true);
    const { fetchFn, seen } = recordingFetch();
    await new HttpClient({
      baseUrl: BASE,
      fetch: fetchFn,
      authToken: async () => jwtish(),
    }).getJson("/worlds");
    expect(seen[0]?.headers.get(CHANNEL)).toBe("mobile_web");
  });

  it("SEC-15 SIGNIN on a wide window it sends no channel header (the API defaults to web)", async () => {
    phone(false);
    const { fetchFn, seen } = recordingFetch();
    await new HttpClient({
      baseUrl: BASE,
      fetch: fetchFn,
      authToken: async () => jwtish(),
    }).getJson("/worlds");
    expect(seen[0]?.headers.has(CHANNEL)).toBe(false);
  });
});

describe("SEC-15 SIGNIN the token reaches every client the app builds", () => {
  it("SEC-15 SIGNIN chooseClient hands authToken to the HTTP client and never asks it for the fixture client", async () => {
    const { fetchFn, seen } = recordingFetch();
    vi.stubGlobal("fetch", fetchFn);
    const getter = vi.fn(async () => jwtish());
    const http = chooseClient({ apiUrl: BASE, search: "", authToken: getter });
    await settle(http.listCards("w_1"));
    expect(seen[0]?.headers.get(AUTH)).toBe(`Bearer ${jwtish()}`);

    const fixtureGetter = vi.fn(async () => jwtish());
    const fixture = chooseClient({ apiUrl: undefined, search: "", authToken: fixtureGetter });
    expect(fixture).toBeInstanceOf(FixtureClient);
    expect(fixtureGetter).not.toHaveBeenCalled();
  });

  it("SEC-15 SIGNIN every Park live request carries the token, and parkApi gives it to the live Api only", async () => {
    const { fetchFn, seen } = recordingFetch();
    const api = createLiveApi({
      baseUrl: BASE,
      fetch: fetchFn,
      authToken: async () => jwtish("park"),
    });
    await settle(api.getLedger());
    await settle(api.getWorlds({}, []));
    expect(seen.length).toBeGreaterThanOrEqual(2);
    expect(seen.filter((r) => r.headers.get(AUTH) !== `Bearer ${jwtish("park")}`)).toEqual([]);

    const recorded = recordingFetch();
    vi.stubGlobal("fetch", recorded.fetchFn);
    const live = parkApi({ VITE_TILO_API_URL: BASE }, undefined, async () => jwtish("select"));
    await settle(live.getWorlds({}, []));
    expect(recorded.seen[0]?.headers.get(AUTH)).toBe(`Bearer ${jwtish("select")}`);

    const fixtureGetter = vi.fn(async () => jwtish());
    for (const env of [{}, { VITE_TILO_API_URL: "" }, { VITE_TILO_API_URL: "  " }]) {
      await parkApi(env, undefined, fixtureGetter).getWorlds({}, []);
    }
    expect(fixtureGetter).not.toHaveBeenCalled();
    expect(recorded.seen).toHaveLength(1);
  });

  it("SEC-15 SIGNIN the page-wide getter comes from the one sign-in session and reaches the Park provider", () => {
    const provider = readFileSync(join(__dirname, "ClientProvider.tsx"), "utf8");
    expect(provider).toMatch(/export const authToken\b/);
    expect(provider).toMatch(/authToken/); // handed to chooseClient too
    expect(provider).toMatch(/chooseClient\(\{[^}]*\bauthToken\b[^}]*\}\)/);
    const context = readFileSync(join(__dirname, "..", "park", "app", "context.tsx"), "utf8");
    expect(context).toMatch(/\{[^}]*\bauthToken\b[^}]*\} from "..\/..\/api\/ClientProvider"/);
    expect(context).toMatch(/parkApi\([^)]*appCheckToken,\s*authToken\)/);
  });
});
