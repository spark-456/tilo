// WIRE-1 (Park wiring, first slice): the live Api reads `GET {base}/costs` for getLedger and nothing else.
// Interface pinned here, for the builder:
//   createLiveApi(options?: { baseUrl?: string; fetch?: typeof fetch }): Api
// - `baseUrl` is the API origin, trailing slashes trimmed, exactly as `HttpClientOptions.baseUrl` in
//   src/api/http.ts (same trim, same `fetch` injection). `fetch` defaults to the GLOBAL fetch looked up at call
//   time (`(url, init) => fetch(url, init)`), so `vi.stubGlobal("fetch", ...)` works for `parkApi(env)`.
// - no `baseUrl` (createLiveApi() as today): getLedger stays NotBuilt and nothing is fetched, so the existing
//   WEB_1a tests and the page tests that mount `createLiveApi()` keep passing.
// - `parkApi({ VITE_TILO_API_URL })` passes its (trimmed) url as `baseUrl`; blank still gives the fixture Api.
// - http.ts holds and sends no credentials ("No sign-in: the API's own principal dependency decides"), so no
//   Authorization header is sent either.
// - failures reject with `TiloApiError` from src/api/http.ts (the shared seam): `status` the HTTP status or null,
//   `retryable` true for 5xx, network failure and an unreadable body, false for 4xx. Never `NotBuilt`, never a
//   resolved fixture value. A 200 whose body is not a cost report (no `totals` object) is an unreadable reply.
// Ambiguity (PRD default, BQ-WIRE1-1): TiloApiError is the "typed error"; no new error class is invented.
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import fc from "fast-check";
import { afterEach, describe, expect, it, vi } from "vitest";
import { callTable, invoke } from "../../../test-support/park/apiCalls";
import { TiloApiError } from "../../api/http";
import { API_METHODS } from "./index";
import { NotBuilt, createLiveApi } from "./liveApi";
import { parkApi } from "./select";

const BASE = "https://api.example.test";
const REPORT = {
  credit_usd: 0.005,
  totals: { tasks: 1, completed_tasks: 1, credits: 242, usd: 1.21, credits_saved: 0, usd_saved: 0 },
  tasks: [
    {
      run_id: "run-a",
      tier: "outpost",
      completed: true,
      credits: 242,
      usd: 1.21,
      credits_saved: 0,
    },
  ],
  by_tier: [
    { tier: "outpost", tasks: 1, credits: 242, usd: 1.21, credits_per_task: 242, credits_saved: 0 },
  ],
  by_profile: [{ profile: "fast", tasks: 1, credits: 242, usd: 1.21, credits_per_task: 242 }],
  by_task_type: [
    { task_type: "research", tasks: 1, credits: 242, usd: 1.21, credits_per_task: 242 },
  ],
  by_tier_profile: [],
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const okFetch = () =>
  vi.fn(async (_url: string | URL | Request, _init?: RequestInit) => json(REPORT));
const asFetch = (f: unknown) => f as typeof fetch;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WIRE_1_live_getLedger: GET /costs as live data", () => {
  it("WIRE_1_getLedger_reads_costs_as_live", async () => {
    const fetchSpy = okFetch();
    const api = createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) });
    const result = await api.getLedger();
    const { ledgerFromCosts } = await import("./live/ledgerFromCosts");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0] ?? [];
    expect(String(url)).toBe(`${BASE}/costs`);
    expect(init?.method ?? "GET").toBe("GET");
    expect(init?.body).toBeUndefined();
    expect(result.source).toBe("live");
    expect(result.data).toEqual(ledgerFromCosts(REPORT));
    expect(result.data.spent).toBeCloseTo(1.21, 10);
  });

  it("WIRE_1_getLedger_trims_trailing_slashes_of_the_base_url", async () => {
    const fetchSpy = okFetch();
    await createLiveApi({ baseUrl: `${BASE}//`, fetch: asFetch(fetchSpy) }).getLedger();
    expect(String(fetchSpy.mock.calls[0]?.[0])).toBe(`${BASE}/costs`);
  });

  it("WIRE_1_getLedger_sends_no_authorization_header_as_http_ts_holds_no_credentials", async () => {
    const fetchSpy = okFetch();
    await createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) }).getLedger();
    const headers = new Headers(fetchSpy.mock.calls[0]?.[1]?.headers);
    expect(headers.has("authorization")).toBe(false);
  });

  it("WIRE_1_getLedger_without_a_base_url_stays_NotBuilt_and_fetches_nothing", async () => {
    const fetchSpy = okFetch();
    vi.stubGlobal("fetch", fetchSpy);
    await expect(createLiveApi().getLedger()).rejects.toBeInstanceOf(NotBuilt);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("WIRE_1_live_api: every other method is still NotBuilt", () => {
  it("WIRE_1_every_method_but_getLedger_rejects_NotBuilt_and_never_touches_the_network", async () => {
    const fetchSpy = okFetch();
    const api = createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) });
    const args = callTable();
    // WIRE-2 connects getWorlds, WIRE-3 getDecisions and decide (liveApi.wire2/wire3.test.ts): they leave this list.
    for (const m of API_METHODS.filter(
      (x) =>
        ![
          "getLedger",
          "getWorlds",
          "getDecisions",
          "decide",
          "startWorld",
          "getConnectors",
          "submitFeedback",
          "getProfileSettings",
          "setPref",
        ].includes(x),
    )) {
      const err = await Promise.resolve(invoke(api, m, args)).then(
        (value) => ({ resolved: value }),
        (e: unknown) => e,
      );
      expect(err, `${m} must reject`).not.toHaveProperty("resolved");
      expect(err, `${m}`).toBeInstanceOf(NotBuilt);
      expect((err as NotBuilt).code, `${m}`).toBe("not_built");
    }
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("WIRE_1_live_getLedger: failures are typed and never become fixture data", () => {
  it.each([400, 401, 403, 404, 422, 500, 503])(
    "WIRE_1_getLedger_http_%i_rejects_TiloApiError_not_NotBuilt_not_data",
    async (status) => {
      const fetchSpy = vi.fn(async () => json({ detail: "private server text" }, status));
      const api = createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) });
      const err = await api.getLedger().then(
        (value) => ({ resolved: value }),
        (e: unknown) => e,
      );
      expect(err).not.toHaveProperty("resolved");
      expect(err).not.toBeInstanceOf(NotBuilt);
      expect(err).toBeInstanceOf(TiloApiError);
      expect((err as TiloApiError).status).toBe(status);
      expect((err as TiloApiError).retryable).toBe(status >= 500);
    },
  );

  it("WIRE_1_getLedger_network_failure_rejects_TiloApiError_without_the_host", async () => {
    const fetchSpy = vi.fn(async () => {
      throw new TypeError("connect ECONNREFUSED 10.0.0.7:8080");
    });
    const err = await createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) })
      .getLedger()
      .then(
        (value) => ({ resolved: value }),
        (e: unknown) => e,
      );
    expect(err).not.toHaveProperty("resolved");
    expect(err).not.toBeInstanceOf(NotBuilt);
    expect(err).toBeInstanceOf(TiloApiError);
    expect((err as TiloApiError).status).toBeNull();
    expect((err as TiloApiError).retryable).toBe(true);
    expect((err as TiloApiError).message).not.toContain("10.0.0.7");
  });

  it.each([
    ["an array", "[]"],
    ["an empty object", "{}"],
    ["a null", "null"],
    ["a string", '"ok"'],
    ["totals that are not an object", '{"totals": 5}'],
    ["text that is not JSON", "<html>gateway</html>"],
  ])("WIRE_1_getLedger_a_200_with_%s_is_an_unreadable_reply_not_data", async (_name, body) => {
    const fetchSpy = vi.fn(async () => new Response(body, { status: 200 }));
    const err = await createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) })
      .getLedger()
      .then(
        (value) => ({ resolved: value }),
        (e: unknown) => e,
      );
    expect(err, "a body that is not a cost report must not become a Ledger").not.toHaveProperty(
      "resolved",
    );
    expect(err).not.toBeInstanceOf(NotBuilt);
    expect(err).toBeInstanceOf(TiloApiError);
  });

  it("WIRE_1_getLedger_property_any_error_status_rejects_and_resolves_nothing", async () => {
    await fc.assert(
      fc.asyncProperty(fc.integer({ min: 300, max: 599 }), async (status) => {
        const fetchSpy = vi.fn(async () => new Response("{}", { status }));
        const outcome = await createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) })
          .getLedger()
          .then(
            () => "resolved",
            (e: unknown) => (e instanceof TiloApiError ? "typed" : "other"),
          );
        expect(outcome).toBe("typed");
      }),
      { numRuns: 40 },
    );
  });
});

describe("WIRE_1_parkApi: the url reaches the live Api", () => {
  it("WIRE_1_parkApi_with_a_url_getLedger_calls_costs_on_the_global_fetch_and_says_live", async () => {
    const fetchSpy = okFetch();
    vi.stubGlobal("fetch", fetchSpy);
    const result = await parkApi({ VITE_TILO_API_URL: `  ${BASE}/  ` }).getLedger();
    expect(String(fetchSpy.mock.calls[0]?.[0])).toBe(`${BASE}/costs`);
    expect(result.source).toBe("live");
    expect(result.data.spent).toBeCloseTo(1.21, 10);
  });

  it("WIRE_1_parkApi_without_a_url_is_still_the_fixture_api_and_fetches_nothing", async () => {
    const fetchSpy = okFetch();
    vi.stubGlobal("fetch", fetchSpy);
    for (const env of [{}, { VITE_TILO_API_URL: "" }, { VITE_TILO_API_URL: "  " }]) {
      expect((await parkApi(env).getLedger()).source).toBe("fixture");
    }
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("WIRE_1_live_api_honesty: the live code cannot reach a fixture (HR-1..HR-7)", () => {
  const apiDir = __dirname;
  const liveDir = join(apiDir, "live");
  const sources = (): string[] =>
    [join(apiDir, "liveApi.ts")].concat(
      existsSync(liveDir)
        ? readdirSync(liveDir)
            .filter((f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f))
            .map((f) => join(liveDir, f))
        : [],
    );

  it("WIRE_1_the_mapper_file_exists_next_to_the_live_api", () => {
    expect(existsSync(join(liveDir, "ledgerFromCosts.ts"))).toBe(true);
  });

  it("WIRE_1_liveApi_and_everything_under_live_import_no_fixture_and_no_fixtureApi", () => {
    for (const file of sources()) {
      const src = readFileSync(file, "utf8");
      expect(src, file).not.toMatch(/from\s+["'](?:\.\.?\/)+(?:live\/)?fixtures/);
      expect(src, file).not.toMatch(/from\s+["'](?:\.\.?\/)+fixtureApi/);
      expect(src, file).not.toMatch(/from\s+["'][^"']*\/(?:screens|world|stage)\//);
    }
  });
});
