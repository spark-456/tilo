// WIRE-2 (Park wiring, second slice; FR-WLD-08, S-14; services/api/tests/API_S_14_WORLDS_LIST.md): the live Api's
// `getWorlds(dec, added)` reads `GET {base}/worlds`. Interface pinned here, for the builder:
// - request: `GET {base}/worlds?limit=100` (first page, no `cursor`). While the body's `next_cursor` is a string, the
//   next request is the same URL plus `cursor=<next_cursor>`, URL-encoded (opaque: never parsed or edited). The walk
//   stops when `next_cursor` is null, or after MAX_PAGES = 10 pages (BQ-WIRE2-5); at the cap the worlds read so
//   far are returned (newest first, so the cap keeps the most recent 1,000), never a hang.
// - result `{ data: World[], source: "live" }`; each item goes through `worldsFromList` (live/worldsFromList.ts),
//   the pages concatenated in order.
// - `dec` is ignored: the list carries no decision state, and `needs` comes only from recorded open cards, never
//   from a local flag (BQ-WIRE2-4, HR-1). `added` (worlds started in this session) is kept as the fixture Api keeps
//   it: first, in the order given, then the live worlds; a live world with the same id as an added one wins and the
//   added one is dropped (BQ-WIRE2-4).
// - a 200 body that is not `{worlds: array of {world_id: string, status: one of the 5 statuses, ...}, next_cursor:
//   string|null}` (including an unknown status, HR-5) rejects `TiloApiError` (status 200, retryable true), on any page.
// - HTTP and network failures on any page reject `TiloApiError` as in WIRE-1; no partial list is returned.
// - no `baseUrl`: getWorlds stays NotBuilt and nothing is fetched. Every other method but getLedger stays NotBuilt.
// - no credentials are sent (http.ts holds none).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import fc from "fast-check";
import { afterEach, describe, expect, it, vi } from "vitest";
import { callTable, invoke } from "../../../test-support/park/apiCalls";
import { TiloApiError } from "../../api/http";
import { API_METHODS } from "./index";
import type { WorldListItem } from "./live/worldsFromList";
import { NotBuilt, createLiveApi } from "./liveApi";
import { parkApi } from "./select";
import type { World } from "./types";

const BASE = "https://api.example.test";
const DEC = { depot: true, mail: false };
const asFetch = (f: unknown) => f as typeof fetch;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const entry = (n: number, over: Record<string, unknown> = {}) => ({
  world_id: `w-${n}`,
  title: `World ${n}`,
  status: "started",
  created_at: "2026-10-07T09:30:00Z",
  last_seq: n,
  ...over,
});
const page = (worlds: unknown[], next: string | null = null) => ({ worlds, next_cursor: next });

/** A fake tilo-api: `pages[cursor]` is the body for that cursor ("" is the first page). */
function pagedFetch(pages: Record<string, unknown>) {
  return vi.fn(async (url: string | URL | Request, _init?: RequestInit) => {
    const u = new URL(String(url));
    const body = pages[u.searchParams.get("cursor") ?? ""];
    return body === undefined ? json({ detail: "bad_cursor" }, 400) : json(body);
  });
}
const urlsOf = (spy: ReturnType<typeof pagedFetch>): URL[] =>
  spy.mock.calls.map(([u]) => new URL(String(u)));
const settle = <T>(p: Promise<T>) =>
  p.then(
    (value) => ({ resolved: value }),
    (e: unknown) => e,
  );
const stubWorld = (id: string): World => ({
  id,
  name: `Added ${id}`,
  short: `Added ${id}`,
  tier: "Town",
  tool: "",
  st: "running",
  agents: 0,
  spend: "",
  spendV: 0,
  nextL: "",
  nextV: "",
  owner: "",
  started: "",
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WIRE_2_live_getWorlds: GET /worlds as live data", () => {
  it("WIRE_2_getWorlds_reads_worlds_with_limit_100_and_says_live", async () => {
    const fetchSpy = pagedFetch({
      "": page([entry(1), entry(2, { title: null, status: "completed" })]),
    });
    const result = await createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) }).getWorlds(
      DEC,
      [],
    );
    const { worldsFromList } = await import("./live/worldsFromList");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const url = urlsOf(fetchSpy)[0] as URL;
    expect(url.origin + url.pathname).toBe(`${BASE}/worlds`);
    expect(url.searchParams.get("limit")).toBe("100");
    expect(url.searchParams.has("cursor")).toBe(false);
    const init = fetchSpy.mock.calls[0]?.[1];
    expect(init?.method ?? "GET").toBe("GET");
    expect(init?.body).toBeUndefined();
    expect(new Headers(init?.headers).has("authorization")).toBe(false);
    expect(result.source).toBe("live");
    expect(result.data).toEqual(
      worldsFromList([entry(1), entry(2, { title: null, status: "completed" })] as WorldListItem[]),
    );
    expect(result.data.map((w) => w.id)).toEqual(["w-1", "w-2"]);
  });

  it("WIRE_2_getWorlds_trims_trailing_slashes_of_the_base_url", async () => {
    const fetchSpy = pagedFetch({ "": page([]) });
    await createLiveApi({ baseUrl: `${BASE}//`, fetch: asFetch(fetchSpy) }).getWorlds(DEC, []);
    const url = urlsOf(fetchSpy)[0] as URL;
    expect(url.origin + url.pathname).toBe(`${BASE}/worlds`);
  });

  it("WIRE_2_getWorlds_an_empty_list_is_an_empty_live_result_not_a_fixture", async () => {
    const result = await createLiveApi({
      baseUrl: BASE,
      fetch: asFetch(pagedFetch({ "": page([]) })),
    }).getWorlds(DEC, []);
    expect(result).toEqual({ data: [], source: "live" });
  });

  it("WIRE_2_getWorlds_walks_next_cursor_pages_in_order", async () => {
    const fetchSpy = pagedFetch({
      "": page([entry(1), entry(2)], "c-1"),
      "c-1": page([entry(3)], "c-2"),
      "c-2": page([entry(4)], null),
    });
    const result = await createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) }).getWorlds(
      DEC,
      [],
    );
    expect(result.data.map((w) => w.id)).toEqual(["w-1", "w-2", "w-3", "w-4"]);
    const urls = urlsOf(fetchSpy);
    expect(urls).toHaveLength(3);
    expect(urls.map((u) => u.searchParams.get("cursor"))).toEqual([null, "c-1", "c-2"]);
    for (const u of urls) expect(u.searchParams.get("limit")).toBe("100");
  });

  it("WIRE_2_getWorlds_sends_the_cursor_back_opaquely_and_url_encoded", async () => {
    const odd = "a+b/c=d&e f?g#h%20é";
    const fetchSpy = pagedFetch({ "": page([entry(1)], odd), [odd]: page([entry(2)]) });
    const result = await createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) }).getWorlds(
      DEC,
      [],
    );
    expect(result.data.map((w) => w.id)).toEqual(["w-1", "w-2"]);
    const second = String(fetchSpy.mock.calls[1]?.[0]);
    expect(new URL(second).searchParams.get("cursor")).toBe(odd);
    // No raw delimiter of the query or fragment leaks out of the value.
    const query = second.split("?")[1] ?? "";
    expect(query).not.toMatch(/[ #]/);
    expect(query.split("&")).toHaveLength(2);
    expect(query).toContain("%2B"); // a literal plus must not survive as "+" (it would read back as a space)
    expect(query).toContain("%26"); // nor a literal ampersand
    expect(query).toContain("%2520"); // a literal percent sign is itself encoded
  });

  it("WIRE_2_getWorlds_property_any_page_split_returns_every_world_once_in_order", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 0, max: 40 }),
        fc.integer({ min: 1, max: 9 }),
        async (raw, size) => {
          const total = Math.min(raw, size * 10); // within the 10-page cap, tested on its own below
          const all = Array.from({ length: total }, (_, i) => entry(i));
          const pages: Record<string, unknown> = {};
          for (let at = 0, n = 0; at === 0 || at < total; at += size, n++) {
            const next = at + size < total ? `cur-${n + 1}` : null;
            pages[n === 0 ? "" : `cur-${n}`] = page(all.slice(at, at + size), next);
          }
          const fetchSpy = pagedFetch(pages);
          const out = await createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) }).getWorlds(
            DEC,
            [],
          );
          expect(out.data.map((w) => w.id)).toEqual(all.map((w) => w.world_id));
        },
      ),
      { numRuns: 40 },
    );
  });

  it("WIRE_2_getWorlds_stops_after_10_pages_when_the_server_never_ends_the_walk", async () => {
    let n = 0;
    const fetchSpy = vi.fn(async () => {
      n += 1;
      return json(page([entry(n)], `cur-${n}`));
    });
    const result = await createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) }).getWorlds(
      DEC,
      [],
    );
    expect(fetchSpy).toHaveBeenCalledTimes(10);
    expect(result.source).toBe("live");
    expect(result.data.map((w) => w.id)).toEqual(
      Array.from({ length: 10 }, (_, i) => `w-${i + 1}`),
    );
  });

  it("WIRE_2_getWorlds_a_server_that_repeats_one_cursor_still_ends_at_the_cap", async () => {
    const fetchSpy = vi.fn(async () => json(page([entry(1)], "same")));
    const out = await createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) }).getWorlds(DEC, []);
    expect(fetchSpy.mock.calls.length).toBeLessThanOrEqual(10);
    expect(out.source).toBe("live");
  });
});

describe("WIRE_2_live_getWorlds: dec and added", () => {
  it("WIRE_2_getWorlds_ignores_dec_no_decision_flag_changes_a_live_world", async () => {
    const make = () =>
      createLiveApi({ baseUrl: BASE, fetch: asFetch(pagedFetch({ "": page([entry(1)]) })) });
    const a = await make().getWorlds({ depot: false, mail: false }, []);
    const b = await make().getWorlds({ depot: true, mail: true }, []);
    expect(b.data).toEqual(a.data);
    expect(b.data.some((w) => w.st === "needs")).toBe(false);
  });

  it("WIRE_2_getWorlds_added_worlds_come_first_in_the_order_given_then_the_live_ones", async () => {
    const fetchSpy = pagedFetch({ "": page([entry(1), entry(2)]) });
    const added = [stubWorld("new2"), stubWorld("new1")];
    const out = await createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) }).getWorlds(
      DEC,
      added,
    );
    expect(out.data.map((w) => w.id)).toEqual(["new2", "new1", "w-1", "w-2"]);
    expect(out.data[0]).toEqual(added[0]);
    expect(out.source).toBe("live");
  });

  it("WIRE_2_getWorlds_a_live_world_with_an_added_id_wins_and_the_added_copy_is_dropped", async () => {
    const fetchSpy = pagedFetch({ "": page([entry(1, { title: "From the server" })]) });
    const out = await createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) }).getWorlds(DEC, [
      { ...stubWorld("w-1"), name: "Local copy", short: "Local copy" },
      stubWorld("new1"),
    ]);
    expect(out.data.map((w) => w.id)).toEqual(["new1", "w-1"]);
    expect(out.data.find((w) => w.id === "w-1")?.name).toBe("From the server");
  });

  it("WIRE_2_getWorlds_does_not_mutate_the_added_array", async () => {
    const added = [stubWorld("new1")];
    const before = JSON.stringify(added);
    await createLiveApi({
      baseUrl: BASE,
      fetch: asFetch(pagedFetch({ "": page([entry(1)]) })),
    }).getWorlds(DEC, added);
    expect(JSON.stringify(added)).toBe(before);
    expect(added).toHaveLength(1);
  });
});

describe("WIRE_2_live_getWorlds: failures are typed and never become fixture data", () => {
  it.each([400, 401, 403, 404, 422, 500, 503])(
    "WIRE_2_getWorlds_http_%i_rejects_TiloApiError_not_NotBuilt_not_data",
    async (status) => {
      const fetchSpy = vi.fn(async () => json({ detail: "private server text" }, status));
      const err = await settle(
        createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) }).getWorlds(DEC, []),
      );
      expect(err).not.toHaveProperty("resolved");
      expect(err).not.toBeInstanceOf(NotBuilt);
      expect(err).toBeInstanceOf(TiloApiError);
      expect((err as TiloApiError).status).toBe(status);
      expect((err as TiloApiError).retryable).toBe(status >= 500);
    },
  );

  it("WIRE_2_getWorlds_a_failing_second_page_rejects_with_no_partial_list", async () => {
    // "c-1" is unknown to the fake, which answers 400 bad_cursor as the API does.
    const fetchSpy = pagedFetch({ "": page([entry(1)], "c-1") });
    const err = await settle(
      createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) }).getWorlds(DEC, []),
    );
    expect(err).not.toHaveProperty("resolved");
    expect(err).toBeInstanceOf(TiloApiError);
    expect((err as TiloApiError).status).toBe(400);
    expect((err as TiloApiError).retryable).toBe(false);
  });

  it("WIRE_2_getWorlds_network_failure_rejects_TiloApiError_without_the_host", async () => {
    const fetchSpy = vi.fn(async () => {
      throw new TypeError("connect ECONNREFUSED 10.0.0.7:8080");
    });
    const err = await settle(
      createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) }).getWorlds(DEC, []),
    );
    expect(err).toBeInstanceOf(TiloApiError);
    expect((err as TiloApiError).status).toBeNull();
    expect((err as TiloApiError).retryable).toBe(true);
    expect((err as TiloApiError).message).not.toContain("10.0.0.7");
  });

  const BAD_BODIES: [string, unknown][] = [
    ["an array", []],
    ["an empty object", {}],
    ["a null", null],
    ["a string", "ok"],
    ["worlds that is not an array", { worlds: {}, next_cursor: null }],
    ["worlds missing", { next_cursor: null }],
    ["a next_cursor that is a number", { worlds: [], next_cursor: 7 }],
    ["an item that is null", { worlds: [null], next_cursor: null }],
    [
      "an item with no world_id",
      { worlds: [{ ...entry(1), world_id: undefined }], next_cursor: null },
    ],
    [
      "an item whose world_id is a number",
      { worlds: [entry(1, { world_id: 4 })], next_cursor: null },
    ],
    [
      "an item with an unknown status",
      { worlds: [entry(1, { status: "archived" })], next_cursor: null },
    ],
    ["an item whose title is a number", { worlds: [entry(1, { title: 3 })], next_cursor: null }],
  ];

  it.each(BAD_BODIES)(
    "WIRE_2_getWorlds_a_200_with_%s_is_an_unreadable_reply_not_data",
    async (_n, body) => {
      const fetchSpy = vi.fn(async () => json(body));
      const err = await settle(
        createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) }).getWorlds(DEC, []),
      );
      expect(err, "a body that is not a world list must not become worlds").not.toHaveProperty(
        "resolved",
      );
      expect(err).not.toBeInstanceOf(NotBuilt);
      expect(err).toBeInstanceOf(TiloApiError);
      expect((err as TiloApiError).status).toBe(200);
      expect((err as TiloApiError).retryable).toBe(true);
    },
  );

  it("WIRE_2_getWorlds_text_that_is_not_json_is_an_unreadable_reply", async () => {
    const fetchSpy = vi.fn(async () => new Response("<html>gateway</html>", { status: 200 }));
    const err = await settle(
      createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) }).getWorlds(DEC, []),
    );
    expect(err).toBeInstanceOf(TiloApiError);
  });

  it("WIRE_2_getWorlds_an_unreadable_second_page_rejects_with_no_partial_list", async () => {
    const fetchSpy = pagedFetch({
      "": page([entry(1)], "c-1"),
      "c-1": { worlds: [entry(2, { status: "archived" })], next_cursor: null },
    });
    const err = await settle(
      createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) }).getWorlds(DEC, []),
    );
    expect(err).not.toHaveProperty("resolved");
    expect(err).toBeInstanceOf(TiloApiError);
  });

  it("WIRE_2_getWorlds_property_any_error_status_rejects_and_resolves_nothing", async () => {
    await fc.assert(
      fc.asyncProperty(fc.integer({ min: 300, max: 599 }), async (status) => {
        const fetchSpy = vi.fn(async () => new Response("{}", { status }));
        const outcome = await createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) })
          .getWorlds(DEC, [])
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

describe("WIRE_2_live_api: nothing else is connected", () => {
  it("WIRE_2_getWorlds_without_a_base_url_stays_NotBuilt_and_fetches_nothing", async () => {
    const fetchSpy = pagedFetch({ "": page([entry(1)]) });
    vi.stubGlobal("fetch", fetchSpy);
    await expect(createLiveApi().getWorlds(DEC, [])).rejects.toBeInstanceOf(NotBuilt);
    await expect(createLiveApi({ baseUrl: "  " }).getWorlds(DEC, [])).rejects.toBeInstanceOf(
      NotBuilt,
    );
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("WIRE_2_every_method_but_getLedger_and_getWorlds_rejects_NotBuilt_and_never_touches_the_network", async () => {
    const fetchSpy = pagedFetch({ "": page([entry(1)]) });
    const api = createLiveApi({ baseUrl: BASE, fetch: asFetch(fetchSpy) });
    const args = callTable();
    for (const m of API_METHODS.filter(
      (x) =>
        ![
          "getLedger",
          "getWorlds",
          "getDecisions",
          "decide",
          "getTeamLive",
          "writeTeam",
          "startWorld",
          "getConnectors",
          "getNotifications",
          "getTeam",
          "getAgenda",
          "submitFeedback",
          "getProfileSettings",
          "getSkills",
          "getLearn",
          "saveSkill",
          "captureSkill",
          "proposeVersion",
          "setPref",
          "getUserSettings",
          "saveUserSettings",
        ].includes(x),
    )) {
      const err = await Promise.resolve(invoke(api, m, args)).then(
        (value) => ({ resolved: value }),
        (e: unknown) => e,
      );
      expect(err, `${m} must reject`).not.toHaveProperty("resolved");
      expect(err, `${m}`).toBeInstanceOf(NotBuilt);
    }
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("WIRE_2_parkApi: the url reaches getWorlds", () => {
  it("WIRE_2_parkApi_with_a_url_getWorlds_calls_worlds_on_the_global_fetch_and_says_live", async () => {
    const fetchSpy = pagedFetch({ "": page([entry(1)]) });
    vi.stubGlobal("fetch", fetchSpy);
    const result = await parkApi({ VITE_TILO_API_URL: `  ${BASE}/  ` }).getWorlds(DEC, []);
    const url = urlsOf(fetchSpy)[0] as URL;
    expect(url.origin + url.pathname).toBe(`${BASE}/worlds`);
    expect(result.source).toBe("live");
    expect(result.data.map((w) => w.id)).toEqual(["w-1"]);
  });

  it("WIRE_2_parkApi_without_a_url_getWorlds_is_the_fixture_api_and_fetches_nothing", async () => {
    const fetchSpy = pagedFetch({ "": page([entry(1)]) });
    vi.stubGlobal("fetch", fetchSpy);
    expect((await parkApi({}).getWorlds(DEC, [])).source).toBe("fixture");
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("WIRE_2_live_api_honesty: the live code cannot reach a fixture (HR-1..HR-7)", () => {
  const live = join(__dirname, "live");
  it("WIRE_2_worldsFromList_imports_no_fixture_screen_world_or_stage_code", () => {
    const src = readFileSync(join(live, "worldsFromList.ts"), "utf8");
    expect(src).not.toMatch(/from\s+["'](?:\.\.?\/)+(?:live\/)?fixtures/);
    expect(src).not.toMatch(/from\s+["'](?:\.\.?\/)+fixtureApi/);
    expect(src).not.toMatch(/from\s+["'][^"']*\/(?:screens|world|stage)\//);
  });

  it("WIRE_2_liveApi_still_imports_no_fixture", () => {
    const src = readFileSync(join(__dirname, "liveApi.ts"), "utf8");
    expect(src).not.toMatch(/from\s+["'](?:\.\.?\/)+(?:live\/)?fixtures/);
    expect(src).not.toMatch(/from\s+["'](?:\.\.?\/)+fixtureApi/);
  });
});
