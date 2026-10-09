// WIRE-3 (Park wiring, third slice; S-06, FR-HIL-01, FR-HIL-02, FR-HIL-11; PRD 9.4 HR-1..HR-7;
// services/api/tests/API_S_06_CARDS_FEED.md, services/api/src/tilo_api/cards.py): the decisions queue goes live on
// tilo-api. Interface pinned here, for the builder (see also live/decisionsFromCards.test.ts):
// getDecisions
// - request: `GET {base}/cards?limit=100` (first page, no `cursor`). While the body's `next_cursor` is a string,
//   the next request is the same URL plus `cursor=<next_cursor>`, URL-encoded (opaque, never parsed). The walk stops
//   when `next_cursor` is null, or after MAX_PAGES = 10 pages as in WIRE-2 (BQ-WIRE3-3); at the cap the cards read so
//   far are returned (oldest first, the ones waiting longest), never a hang. Every call reads again: nothing is cached
//   (FR-HIL-11: an answered card is gone on the very next read).
// - result `{ data: Decision[], source: "live" }`, each item through `decisionsFromCards`, pages concatenated in
//   order. An empty feed is `{ data: [], source: "live" }`. `count` is not used here.
// - a 200 body that is not `{cards: array of {world_id: string, card_id: string, card: <a card>}, next_cursor:
//   string|null}` rejects `TiloApiError` (status 200, retryable true), on any page. A card is unreadable when it is
//   not an object, has an unknown `kind`, lacks `options` (each `{id, label}` strings), `what_happened` or
//   `why_it_matters` as strings, lacks the option a tap answers with (a gate's `approve`, a consent card's
//   `connect`, a question's one `suggested`), or names another world or id than its wrapper (`card.world_id` and
//   `card.id` equal the item's `world_id` and `card_id`). The Api never answers a card it could not read.
// - HTTP and network failures on any page reject `TiloApiError` as in WIRE-1/2; no partial list. Nothing but GET is
//   ever sent while reading, so a read never answers a card (a gate or consent card needs a person).
// decide(key)
// - the key is one the Api itself served in an earlier `getDecisions` (it keeps the way back from `k` to world_id,
//   card_id and the option, BQ-WIRE3-1). A key it never served (a fixture key such as "depot", "", a forged path)
//   rejects `TiloApiError` (retryable false, write false) and sends nothing.
// - one `POST {base}/worlds/{world_id}/cards/{card_id}/answer` (ids URL-encoded, `Content-Type: application/json`),
//   body `{"option": <id>}` (a `channel` of "web" or "mobile_web" is the only other key allowed: no identity, no
//   pin_verified, no context), where the option is a gate's `approve`, a consent card's `connect`, otherwise the
//   `suggested` one (BQ-WIRE3-2). No credentials are sent.
// - `200 {"outcome": "answered"}` resolves `{ data: {ok: true, dec}, source: "live" }` where `dec[k]` is true for
//   this key and every key answered earlier through the same Api instance (as the fixture Api accumulates, BQ-WIRE3-6).
// - nothing else resolves. A 4xx `{outcome: "rejected", reason}` (reasons already_resolved, card_not_found, forbidden,
//   busy, invalid_option, channel_not_permitted, invalid_channel) rejects `TiloApiError` with the served status,
//   retryable false and `write` true, and a plain sentence for the reason (http.ts's, never the raw code). A 200 body
//   `{outcome: "rejected", reason}` is the same error (status 200, retryable false, write true, same sentence). A 5xx
//   (the 503 `{outcome: "error", reason: "event_write_failed"}` included), a network failure and a 200 that is not
//   `{outcome: "answered"}` reject `TiloApiError` with `write` true. Exactly ONE POST per `decide` call, whatever the
//   outcome: no retry, no second request (no double answer), and no refresh GET either.
// undo
// - there is no route that reopens an answered card (first answer wins), so `undo` stays NotBuilt and fetches nothing
//   (BQ-WIRE3-7).
// Everything else
// - no `baseUrl`: getDecisions and decide stay NotBuilt and nothing is fetched. Every method but getLedger, getWorlds,
//   getDecisions and decide stays NotBuilt. No fixture is imported by the live code.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { Card } from "@tilo/contracts";
import fc from "fast-check";
import { afterEach, describe, expect, it, vi } from "vitest";
import { callTable, invoke } from "../../../test-support/park/apiCalls";
import { TiloApiError } from "../../api/http";
import { decisions as fixtureDecisions } from "./fixtures";
import { API_METHODS } from "./index";
import { type CardFeedItem, decisionsFromCards } from "./live/decisionsFromCards";
import { NotBuilt, createLiveApi } from "./liveApi";
import { parkApi } from "./select";
import type { Decision, DecisionKey } from "./types";

const BASE = "https://api.example.test";
const asFetch = (f: unknown) => f as typeof fetch;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const ulid = (n: number) => `01${"0".repeat(21)}${String(n).padStart(3, "0")}`;
const asKey = (s: string) => s as unknown as DecisionKey;

type Over = Record<string, unknown>;

/** A valid card of one kind, shaped like contracts/card.schema.json. */
function card(n: number, kind: Card["kind"] = "needs_you", over: Over = {}): Card {
  const base = {
    id: ulid(n),
    world_id: `w_a${n}`,
    run_id: `r_a${n}`,
    kind,
    rung: kind === "needs_you" ? "needs_you" : kind,
    header: { building: "B1", agent: "A_x" },
    what_happened: `Something happened ${n}`,
    why_it_matters: `It matters because ${n}`,
    add_context: false,
    actions: ["show_me"],
    answer_channels: ["web", "mobile_web"],
    created_at: "2026-10-07T09:30:00.000Z",
    timeout: 3600,
    gate: null,
    consent: null,
  };
  const kinds: Record<string, Over> = {
    needs_you: {
      options: [
        { id: "skip_it", label: "Skip it", suggested: false, irreversible: false },
        { id: "go_on", label: "Go on", suggested: true, reason: "Cheapest.", irreversible: false },
      ],
      safe_default: "go_on",
    },
    meeting: {
      options: [
        { id: "join", label: "Join", suggested: true, reason: "On time.", irreversible: false },
        { id: "skip", label: "Skip", suggested: false, irreversible: false },
      ],
      safe_default: "join",
    },
    gate: {
      options: [
        { id: "approve", label: "Approve", suggested: false, irreversible: true },
        { id: "hold", label: "Hold", suggested: true, reason: "Safe.", irreversible: false },
      ],
      safe_default: "hold",
      gate: {
        id: "G1",
        action: {
          type: "send_email",
          connector: "gmail",
          exact: `Send the brief to the supplier ${n}`,
          item: null,
          destination: null,
        },
        recipients: [`a${n}@example.test`],
        irreversible: true,
        risk_tier: "T3",
      },
    },
    consent: {
      options: [
        { id: "connect", label: "Connect", suggested: false, irreversible: false },
        { id: "hold", label: "Hold", suggested: true, reason: "Nothing yet.", irreversible: false },
      ],
      safe_default: "hold",
      consent: { connector: "gmail", scopes: [`Read mail ${n}`] },
    },
  };
  return { ...base, ...kinds[kind], ...over } as unknown as Card;
}

/** A feed item (the wrapper `GET /cards` serves). */
const entry = (n: number, kind: Card["kind"] = "needs_you", over: Over = {}): CardFeedItem => {
  const c = card(n, kind, over);
  return { world_id: c.world_id, card_id: c.id, card: c };
};
const page = (cards: unknown[], next: string | null = null) => ({
  cards,
  count: cards.length,
  next_cursor: next,
});

interface Fake {
  /** The body for each cursor ("" is the first page); an unknown cursor is a 400 like the API's. */
  pages?: Record<string, unknown>;
  /** The answer route's reply. Default: 200 answered. */
  answer?: (url: URL, init: RequestInit | undefined) => Response | Promise<Response>;
}
/** A fake tilo-api: `GET /cards` pages, and the per-world answer route. */
function fakeApi({ pages = {}, answer }: Fake) {
  return vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const u = new URL(String(url));
    if ((init?.method ?? "GET") === "POST") {
      return answer ? answer(u, init) : json({ outcome: "answered" });
    }
    const body = pages[u.searchParams.get("cursor") ?? ""];
    return body === undefined ? json({ detail: "bad_cursor" }, 400) : json(body);
  });
}
type Spy = ReturnType<typeof fakeApi>;
const callsOf = (spy: Spy, method: "GET" | "POST") =>
  spy.mock.calls.filter(([, init]) => (init?.method ?? "GET") === method);
const urlsOf = (spy: Spy, method: "GET" | "POST" = "GET"): URL[] =>
  callsOf(spy, method).map(([u]) => new URL(String(u)));
const settle = <T>(p: Promise<T>) =>
  p.then(
    (value) => ({ resolved: value }),
    (e: unknown) => e,
  );
const live = (spy: Spy) => createLiveApi({ baseUrl: BASE, fetch: asFetch(spy) });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WIRE_3_live_getDecisions: GET /cards as live data", () => {
  it("WIRE_3_getDecisions_reads_cards_with_limit_100_and_says_live", async () => {
    const items = [entry(1), entry(2, "gate")];
    const spy = fakeApi({ pages: { "": page(items) } });
    const result = await live(spy).getDecisions();
    expect(spy).toHaveBeenCalledTimes(1);
    const url = urlsOf(spy)[0] as URL;
    expect(url.origin + url.pathname).toBe(`${BASE}/cards`);
    expect(url.searchParams.get("limit")).toBe("100");
    expect(url.searchParams.has("cursor")).toBe(false);
    const init = spy.mock.calls[0]?.[1];
    expect(init?.method ?? "GET").toBe("GET");
    expect(init?.body).toBeUndefined();
    expect(new Headers(init?.headers).has("authorization")).toBe(false);
    expect(result.source).toBe("live");
    expect(result.data).toEqual(decisionsFromCards(items));
    expect(result.data.map((d) => d.world)).toEqual([items[0]?.world_id, items[1]?.world_id]);
  });

  it("WIRE_3_getDecisions_trims_trailing_slashes_of_the_base_url", async () => {
    const spy = fakeApi({ pages: { "": page([]) } });
    await createLiveApi({ baseUrl: `${BASE}//`, fetch: asFetch(spy) }).getDecisions();
    const url = urlsOf(spy)[0] as URL;
    expect(url.origin + url.pathname).toBe(`${BASE}/cards`);
  });

  it("WIRE_3_getDecisions_an_empty_feed_is_an_empty_live_result_not_a_fixture", async () => {
    const result = await live(fakeApi({ pages: { "": page([]) } })).getDecisions();
    expect(result).toEqual({ data: [], source: "live" });
  });

  it("WIRE_3_getDecisions_walks_next_cursor_pages_in_order", async () => {
    const spy = fakeApi({
      pages: {
        "": page([entry(1), entry(2)], "c-1"),
        "c-1": page([entry(3)], "c-2"),
        "c-2": page([entry(4)], null),
      },
    });
    const result = await live(spy).getDecisions();
    expect(result.data.map((d) => d.title)).toEqual([
      "Something happened 1",
      "Something happened 2",
      "Something happened 3",
      "Something happened 4",
    ]);
    const urls = urlsOf(spy);
    expect(urls.map((u) => u.searchParams.get("cursor"))).toEqual([null, "c-1", "c-2"]);
    for (const u of urls) expect(u.searchParams.get("limit")).toBe("100");
  });

  it("WIRE_3_getDecisions_sends_the_cursor_back_opaquely_and_url_encoded", async () => {
    const odd = "a+b/c=d&e f?g#h%20é";
    const spy = fakeApi({ pages: { "": page([entry(1)], odd), [odd]: page([entry(2)]) } });
    const result = await live(spy).getDecisions();
    expect(result.data).toHaveLength(2);
    const second = String(spy.mock.calls[1]?.[0]);
    expect(new URL(second).searchParams.get("cursor")).toBe(odd);
    const query = second.split("?")[1] ?? "";
    expect(query).not.toMatch(/[ #]/);
    expect(query.split("&")).toHaveLength(2);
    expect(query).toContain("%2B");
    expect(query).toContain("%26");
    expect(query).toContain("%2520");
  });

  it("WIRE_3_getDecisions_property_any_page_split_returns_every_card_once_in_order", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 0, max: 40 }),
        fc.integer({ min: 1, max: 9 }),
        async (raw, size) => {
          const total = Math.min(raw, size * 10);
          const all = Array.from({ length: total }, (_, i) => entry(i + 1));
          const pages: Record<string, unknown> = {};
          for (let at = 0, n = 0; at === 0 || at < total; at += size, n++) {
            const next = at + size < total ? `cur-${n + 1}` : null;
            pages[n === 0 ? "" : `cur-${n}`] = page(all.slice(at, at + size), next);
          }
          const out = await live(fakeApi({ pages })).getDecisions();
          expect(out.data.map((d) => d.world)).toEqual(all.map((i) => i.world_id));
          expect(new Set(out.data.map((d) => d.k)).size).toBe(total);
        },
      ),
      { numRuns: 40 },
    );
  });

  it("WIRE_3_getDecisions_stops_after_10_pages_when_the_server_never_ends_the_walk", async () => {
    let n = 0;
    const spy = vi.fn(async () => {
      n += 1;
      return json(page([entry(n)], `cur-${n}`));
    });
    const result = await live(spy as unknown as Spy).getDecisions();
    expect(spy).toHaveBeenCalledTimes(10);
    expect(result.source).toBe("live");
    expect(result.data.map((d) => d.title)).toEqual(
      Array.from({ length: 10 }, (_, i) => `Something happened ${i + 1}`),
    );
  });

  it("WIRE_3_getDecisions_a_server_that_repeats_one_cursor_still_ends_at_the_cap", async () => {
    const spy = vi.fn(async () => json(page([entry(1)], "same")));
    const out = await live(spy as unknown as Spy).getDecisions();
    expect(spy.mock.calls.length).toBeLessThanOrEqual(10);
    expect(out.source).toBe("live");
  });

  it("WIRE_3_getDecisions_every_request_is_a_GET_so_a_read_never_answers_a_card", async () => {
    const spy = fakeApi({
      pages: {
        "": page([entry(1), entry(2, "gate"), entry(3, "consent")], "c-1"),
        "c-1": page([entry(4, "meeting")]),
      },
    });
    await live(spy).getDecisions();
    await live(spy).getDecisions();
    expect(callsOf(spy, "POST")).toHaveLength(0);
    for (const [, init] of spy.mock.calls) {
      expect(init?.method ?? "GET").toBe("GET");
      expect(init?.body).toBeUndefined();
    }
  });

  it("WIRE_3_getDecisions_reads_again_on_every_call_so_an_answered_card_is_gone_next_time", async () => {
    let served = [entry(1), entry(2)];
    const spy = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "POST") return json({ outcome: "answered" });
      void url;
      return json(page(served));
    });
    const api = live(spy as unknown as Spy);
    const first = await api.getDecisions();
    expect(first.data).toHaveLength(2);
    served = [entry(2)];
    const second = await api.getDecisions();
    expect(spy.mock.calls.filter(([, i]) => (i?.method ?? "GET") === "GET")).toHaveLength(2);
    expect(second.data.map((d) => d.title)).toEqual(["Something happened 2"]);
  });

  it("WIRE_3_getDecisions_no_fixture_decision_text_appears_in_a_live_result", async () => {
    const out = JSON.stringify(
      await live(fakeApi({ pages: { "": page([entry(1), entry(2, "gate")]) } })).getDecisions(),
    );
    for (const f of fixtureDecisions) {
      for (const text of [f.title, f.body, f.yes, f.done, f.toast, f.approvedTitle]) {
        expect(out).not.toContain(text);
      }
    }
  });
});

describe("WIRE_3_live_getDecisions: failures are typed and never become fixture data", () => {
  it.each([400, 401, 403, 404, 422, 500, 503])(
    "WIRE_3_getDecisions_http_%i_rejects_TiloApiError_not_NotBuilt_not_data",
    async (status) => {
      const spy = vi.fn(async () => json({ detail: "private server text" }, status));
      const err = await settle(live(spy as unknown as Spy).getDecisions());
      expect(err).not.toHaveProperty("resolved");
      expect(err).not.toBeInstanceOf(NotBuilt);
      expect(err).toBeInstanceOf(TiloApiError);
      expect((err as TiloApiError).status).toBe(status);
      expect((err as TiloApiError).retryable).toBe(status >= 500);
    },
  );

  it("WIRE_3_getDecisions_a_failing_second_page_rejects_with_no_partial_list", async () => {
    const spy = fakeApi({ pages: { "": page([entry(1)], "c-1") } }); // "c-1" is a 400 bad_cursor
    const err = await settle(live(spy).getDecisions());
    expect(err).not.toHaveProperty("resolved");
    expect(err).toBeInstanceOf(TiloApiError);
    expect((err as TiloApiError).status).toBe(400);
  });

  it("WIRE_3_getDecisions_network_failure_rejects_TiloApiError_without_the_host", async () => {
    const spy = vi.fn(async () => {
      throw new TypeError("connect ECONNREFUSED 10.0.0.7:8080");
    });
    const err = await settle(live(spy as unknown as Spy).getDecisions());
    expect(err).toBeInstanceOf(TiloApiError);
    expect((err as TiloApiError).status).toBeNull();
    expect((err as TiloApiError).retryable).toBe(true);
    expect((err as TiloApiError).message).not.toContain("10.0.0.7");
  });

  const good = () => entry(1);
  const withCard = (over: Over): unknown => {
    const i = good();
    return { ...i, card: { ...i.card, ...over } };
  };
  const BAD_BODIES: [string, unknown][] = [
    ["an array", []],
    ["an empty object", {}],
    ["a null", null],
    ["a string", "ok"],
    ["cards that is not an array", { cards: {}, count: 0, next_cursor: null }],
    ["cards missing", { count: 0, next_cursor: null }],
    ["a next_cursor that is a number", { cards: [], count: 0, next_cursor: 7 }],
    ["an item that is null", page([null])],
    ["an item with no world_id", page([{ ...good(), world_id: undefined }])],
    ["an item whose card_id is a number", page([{ ...good(), card_id: 4 }])],
    ["an item with no card", page([{ world_id: good().world_id, card_id: good().card_id }])],
    ["a card that is a string", page([{ ...good(), card: "x" }])],
    ["a card of an unknown kind", page([withCard({ kind: "cheque" })])],
    ["a card with no options", page([withCard({ options: undefined })])],
    ["a card whose options are not an array", page([withCard({ options: "go" })])],
    ["an option with no id", page([withCard({ options: [{ label: "Go", suggested: true }] })])],
    ["an option with no label", page([withCard({ options: [{ id: "go", suggested: true }] })])],
    ["a card with no what_happened", page([withCard({ what_happened: undefined })])],
    ["a card whose why_it_matters is a number", page([withCard({ why_it_matters: 3 })])],
    [
      "a question with no suggested option",
      page([
        withCard({
          options: [
            { id: "a", label: "A", suggested: false, irreversible: false },
            { id: "b", label: "B", suggested: false, irreversible: false },
          ],
        }),
      ]),
    ],
    [
      "a gate with no approve option",
      page([{ ...entry(2, "gate"), card: { ...entry(2, "gate").card, options: [] } }]),
    ],
    [
      "a consent card with no connect option",
      page([{ ...entry(3, "consent"), card: { ...entry(3, "consent").card, options: [] } }]),
    ],
    ["an item whose world_id differs from its card", page([{ ...good(), world_id: "w_other" }])],
    ["an item whose card_id differs from its card", page([{ ...good(), card_id: ulid(99) }])],
  ];

  it.each(BAD_BODIES)(
    "WIRE_3_getDecisions_a_200_with_%s_is_an_unreadable_reply_not_data",
    async (_n, body) => {
      const spy = vi.fn(async () => json(body));
      const err = await settle(live(spy as unknown as Spy).getDecisions());
      expect(err, "a body that is not a card feed must not become decisions").not.toHaveProperty(
        "resolved",
      );
      expect(err).not.toBeInstanceOf(NotBuilt);
      expect(err).toBeInstanceOf(TiloApiError);
      expect((err as TiloApiError).status).toBe(200);
      expect((err as TiloApiError).retryable).toBe(true);
    },
  );

  it("WIRE_3_getDecisions_text_that_is_not_json_is_an_unreadable_reply", async () => {
    const spy = vi.fn(async () => new Response("<html>gateway</html>", { status: 200 }));
    const err = await settle(live(spy as unknown as Spy).getDecisions());
    expect(err).toBeInstanceOf(TiloApiError);
  });

  it("WIRE_3_getDecisions_an_unreadable_second_page_rejects_with_no_partial_list", async () => {
    const spy = fakeApi({
      pages: {
        "": page([entry(1)], "c-1"),
        "c-1": { cards: [{ world_id: "w_a2", card_id: ulid(2), card: 5 }], next_cursor: null },
      },
    });
    const err = await settle(live(spy).getDecisions());
    expect(err).not.toHaveProperty("resolved");
    expect(err).toBeInstanceOf(TiloApiError);
  });

  it("WIRE_3_getDecisions_property_any_error_status_rejects_and_resolves_nothing", async () => {
    await fc.assert(
      fc.asyncProperty(fc.integer({ min: 300, max: 599 }), async (status) => {
        const spy = vi.fn(async () => new Response("{}", { status }));
        const outcome = await live(spy as unknown as Spy)
          .getDecisions()
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

/** Read the feed, then return the api and the decisions in order. */
async function served(items: CardFeedItem[], answer?: Fake["answer"]) {
  const spy = fakeApi({ pages: { "": page(items) }, ...(answer ? { answer } : {}) });
  const api = live(spy);
  const { data } = await api.getDecisions();
  return { api, spy, data };
}
const bodyOf = (spy: Spy): Record<string, unknown> =>
  JSON.parse(String(callsOf(spy, "POST")[0]?.[1]?.body)) as Record<string, unknown>;

describe("WIRE_3_live_decide: the person's answer goes to the per-world answer route", () => {
  it("WIRE_3_decide_posts_one_answer_with_the_world_card_and_suggested_option", async () => {
    const items = [entry(1), entry(2)];
    const { api, spy, data } = await served(items);
    const d = data[1] as Decision;
    const result = await api.decide(d.k);
    const posts = callsOf(spy, "POST");
    expect(posts).toHaveLength(1);
    const url = urlsOf(spy, "POST")[0] as URL;
    expect(url.origin + url.pathname).toBe(
      `${BASE}/worlds/${items[1]?.world_id}/cards/${items[1]?.card_id}/answer`,
    );
    const init = posts[0]?.[1];
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("content-type")).toContain("application/json");
    expect(new Headers(init?.headers).has("authorization")).toBe(false);
    expect(bodyOf(spy)).toEqual({ option: "go_on" }); // the suggested option, not the first one listed
    expect(result.source).toBe("live");
    expect(result.data.ok).toBe(true);
    expect(result.data.dec[d.k]).toBe(true);
  });

  it("WIRE_3_decide_a_body_carries_only_the_option_and_at_most_a_web_channel", async () => {
    const { api, spy, data } = await served([entry(1, "gate")]);
    await api.decide((data[0] as Decision).k);
    const body = bodyOf(spy);
    expect(Object.keys(body).every((k) => k === "option" || k === "channel")).toBe(true);
    if ("channel" in body) expect(["web", "mobile_web"]).toContain(body.channel);
    expect(body).not.toHaveProperty("pin_verified");
    expect(body).not.toHaveProperty("user_id");
    expect(body).not.toHaveProperty("by");
  });

  it("WIRE_3_decide_a_gate_card_is_answered_approve_only_when_the_person_decides", async () => {
    const { api, spy, data } = await served([entry(1, "gate"), entry(2, "needs_you")]);
    expect(callsOf(spy, "POST")).toHaveLength(0); // reading the feed answered nothing
    await api.decide((data[0] as Decision).k);
    expect(callsOf(spy, "POST")).toHaveLength(1);
    expect(bodyOf(spy)).toEqual({ option: "approve" }); // hold is the suggested one; approve is the explicit act
    expect(String(urlsOf(spy, "POST")[0])).toContain(`/worlds/${entry(1).world_id}/cards/`);
  });

  it("WIRE_3_decide_a_consent_card_is_answered_connect", async () => {
    const { api, spy, data } = await served([entry(1, "consent")]);
    await api.decide((data[0] as Decision).k);
    expect(bodyOf(spy)).toEqual({ option: "connect" });
  });

  it("WIRE_3_decide_a_meeting_card_is_answered_with_its_suggested_option", async () => {
    const { api, spy, data } = await served([entry(1, "meeting")]);
    await api.decide((data[0] as Decision).k);
    expect(bodyOf(spy)).toEqual({ option: "join" });
  });

  it("WIRE_3_decide_two_worlds_with_the_same_card_id_each_answer_their_own_world", async () => {
    const a = { ...entry(1), world_id: "w_one", card: { ...entry(1).card, world_id: "w_one" } };
    const b = { ...entry(1), world_id: "w_two", card: { ...entry(1).card, world_id: "w_two" } };
    const { api, spy, data } = await served([a, b]);
    expect(data[0]?.k).not.toBe(data[1]?.k);
    await api.decide((data[1] as Decision).k);
    await api.decide((data[0] as Decision).k);
    const paths = urlsOf(spy, "POST").map((u) => u.pathname);
    expect(paths).toEqual([
      `/worlds/w_two/cards/${ulid(1)}/answer`,
      `/worlds/w_one/cards/${ulid(1)}/answer`,
    ]);
  });

  it("WIRE_3_decide_ids_never_make_extra_path_segments", async () => {
    const odd = entry(1, "needs_you", { world_id: "w_a/../x?y#z", id: `${ulid(1)}/..` });
    const spy = fakeApi({ pages: { "": page([odd]) } });
    const api = live(spy);
    const read = await settle(api.getDecisions());
    if (read instanceof TiloApiError) return; // refusing an id that is not an id is as good
    const { resolved } = read as { resolved: { data: Decision[] } };
    await api.decide((resolved.data[0] as Decision).k);
    const u = urlsOf(spy, "POST")[0] as URL;
    expect(u.pathname.split("/")).toHaveLength(6); // "", worlds, <id>, cards, <id>, answer
    expect(u.search).toBe("");
    expect(u.hash).toBe("");
  });

  it("WIRE_3_decide_dec_accumulates_the_keys_answered_through_this_api", async () => {
    const { api, data } = await served([entry(1), entry(2), entry(3)]);
    const first = await api.decide((data[0] as Decision).k);
    const second = await api.decide((data[2] as Decision).k);
    expect(first.data.dec).toEqual({ [(data[0] as Decision).k]: true });
    expect(second.data.dec[(data[0] as Decision).k]).toBe(true);
    expect(second.data.dec[(data[2] as Decision).k]).toBe(true);
    expect(second.data.dec[(data[1] as Decision).k]).toBeUndefined();
  });

  it("WIRE_3_decide_never_reads_the_feed_again_and_never_posts_twice", async () => {
    const { api, spy, data } = await served([entry(1)]);
    await api.decide((data[0] as Decision).k);
    expect(callsOf(spy, "GET")).toHaveLength(1);
    expect(callsOf(spy, "POST")).toHaveLength(1);
  });
});

describe("WIRE_3_live_decide: a key the feed never served sends nothing", () => {
  it.each([["depot"], ["mail"], [""], ["../../admin"], ["w_a1/cards/x"], ["0".repeat(40)]])(
    "WIRE_3_decide_unserved_key_%j_rejects_TiloApiError_and_fetches_nothing",
    async (key) => {
      const spy = fakeApi({ pages: { "": page([entry(1)]) } });
      const api = live(spy);
      await api.getDecisions();
      const before = spy.mock.calls.length;
      const err = await settle(api.decide(asKey(key)));
      expect(err).not.toHaveProperty("resolved");
      expect(err).not.toBeInstanceOf(NotBuilt);
      expect(err).toBeInstanceOf(TiloApiError);
      expect((err as TiloApiError).retryable).toBe(false);
      expect((err as TiloApiError).write).toBe(false);
      expect(spy.mock.calls.length).toBe(before);
    },
  );

  it("WIRE_3_decide_before_any_read_rejects_TiloApiError_and_fetches_nothing", async () => {
    const spy = fakeApi({});
    const err = await settle(live(spy).decide("depot"));
    expect(err).toBeInstanceOf(TiloApiError);
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("WIRE_3_live_decide: the answer route's refusals are typed errors, never success", () => {
  const REASONS: [string, number, string][] = [
    ["already_resolved", 400, "This card was already answered."],
    ["card_not_found", 404, "Tilo could not find that card."],
    ["forbidden", 403, "You do not have access to answer this card."],
    ["busy", 409, "Tilo is busy with this card. Try again in a moment."],
    ["invalid_option", 400, "That option is not offered on this card."],
    ["invalid_channel", 400, "This answer cannot be sent from the web."],
    ["channel_not_permitted", 403, "This answer cannot be sent from the web."],
  ];

  it.each(REASONS)(
    "WIRE_3_decide_rejected_%s_http_%i_is_a_TiloApiError_with_a_plain_sentence",
    async (reason, status, sentence) => {
      const { api, spy, data } = await served([entry(1)], () =>
        json({ outcome: "rejected", reason }, status),
      );
      const err = await settle(api.decide((data[0] as Decision).k));
      expect(err, "a refused answer must not resolve").not.toHaveProperty("resolved");
      expect(err).toBeInstanceOf(TiloApiError);
      const e = err as TiloApiError;
      expect(e.status).toBe(status);
      expect(e.retryable).toBe(false);
      expect(e.write).toBe(true);
      expect(e.message).toBe(sentence);
      expect(e.message).not.toMatch(/_/); // no raw code such as already_resolved
      expect(callsOf(spy, "POST")).toHaveLength(1);
    },
  );

  it("WIRE_3_decide_a_200_that_says_rejected_is_the_same_typed_error_not_success", async () => {
    const { api, spy, data } = await served([entry(1)], () =>
      json({ outcome: "rejected", reason: "already_resolved" }),
    );
    const err = await settle(api.decide((data[0] as Decision).k));
    expect(err).not.toHaveProperty("resolved");
    expect(err).toBeInstanceOf(TiloApiError);
    const e = err as TiloApiError;
    expect(e.status).toBe(200);
    expect(e.retryable).toBe(false);
    expect(e.write).toBe(true);
    expect(e.message).toBe("This card was already answered.");
    expect(callsOf(spy, "POST")).toHaveLength(1);
  });

  it("WIRE_3_decide_a_200_rejected_with_an_unknown_reason_says_no_raw_code", async () => {
    const { api, data } = await served([entry(1)], () =>
      json({ outcome: "rejected", reason: "weird_internal_code_7" }),
    );
    const err = await settle(api.decide((data[0] as Decision).k));
    expect(err).toBeInstanceOf(TiloApiError);
    expect((err as TiloApiError).message.length).toBeGreaterThan(0);
    expect((err as TiloApiError).message).not.toContain("weird_internal_code_7");
    expect((err as TiloApiError).retryable).toBe(false);
  });

  it("WIRE_3_decide_a_failed_answer_leaves_dec_without_the_key_on_the_next_success", async () => {
    let n = 0;
    const { api, data } = await served([entry(1), entry(2)], () =>
      ++n === 1
        ? json({ outcome: "rejected", reason: "busy" }, 409)
        : json({ outcome: "answered" }),
    );
    await settle(api.decide((data[0] as Decision).k));
    const ok = await api.decide((data[1] as Decision).k);
    expect(ok.data.dec[(data[0] as Decision).k]).toBeUndefined();
    expect(ok.data.dec[(data[1] as Decision).k]).toBe(true);
  });
});

describe("WIRE_3_live_decide: failures never retry and never double-answer", () => {
  it.each([500, 502, 503])(
    "WIRE_3_decide_http_%i_rejects_retryable_with_write_true_after_exactly_one_post",
    async (status) => {
      const { api, spy, data } = await served([entry(1)], () =>
        json({ outcome: "error", reason: "event_write_failed" }, status),
      );
      const err = await settle(api.decide((data[0] as Decision).k));
      expect(err).not.toHaveProperty("resolved");
      expect(err).toBeInstanceOf(TiloApiError);
      expect((err as TiloApiError).status).toBe(status);
      expect((err as TiloApiError).retryable).toBe(true);
      expect((err as TiloApiError).write).toBe(true);
      expect(callsOf(spy, "POST")).toHaveLength(1);
      expect(callsOf(spy, "GET")).toHaveLength(1);
    },
  );

  it("WIRE_3_decide_network_failure_rejects_TiloApiError_write_true_without_the_host_after_one_post", async () => {
    const { api, spy, data } = await served([entry(1)], () => {
      throw new TypeError("connect ECONNREFUSED 10.0.0.7:8080");
    });
    const err = await settle(api.decide((data[0] as Decision).k));
    expect(err).toBeInstanceOf(TiloApiError);
    const e = err as TiloApiError;
    expect(e.status).toBeNull();
    expect(e.write).toBe(true);
    expect(e.message).not.toContain("10.0.0.7");
    expect(callsOf(spy, "POST")).toHaveLength(1);
  });

  const BAD_ANSWERS: [string, unknown][] = [
    ["an empty object", {}],
    ["an array", []],
    ["a null", null],
    ["a string", "answered"],
    ["an unknown outcome", { outcome: "maybe" }],
    ["an error outcome", { outcome: "error", reason: "event_write_failed" }],
  ];
  it.each(BAD_ANSWERS)("WIRE_3_decide_a_200_with_%s_is_not_a_success", async (_n, body) => {
    const { api, spy, data } = await served([entry(1)], () => json(body));
    const err = await settle(api.decide((data[0] as Decision).k));
    expect(err).not.toHaveProperty("resolved");
    expect(err).toBeInstanceOf(TiloApiError);
    expect((err as TiloApiError).write).toBe(true);
    expect(callsOf(spy, "POST")).toHaveLength(1);
  });

  it("WIRE_3_decide_text_that_is_not_json_is_not_a_success", async () => {
    const { api, data } = await served(
      [entry(1)],
      () => new Response("<html>x</html>", { status: 200 }),
    );
    const err = await settle(api.decide((data[0] as Decision).k));
    expect(err).not.toHaveProperty("resolved");
    expect(err).toBeInstanceOf(TiloApiError);
    expect((err as TiloApiError).write).toBe(true);
  });

  it("WIRE_3_decide_property_any_non_answered_status_rejects_with_one_post_and_resolves_nothing", async () => {
    await fc.assert(
      fc.asyncProperty(fc.integer({ min: 300, max: 599 }), async (status) => {
        const { api, spy, data } = await served([entry(1)], () => new Response("{}", { status }));
        const outcome = await api.decide((data[0] as Decision).k).then(
          () => "resolved",
          (e: unknown) => (e instanceof TiloApiError ? "typed" : "other"),
        );
        expect(outcome).toBe("typed");
        expect(callsOf(spy, "POST")).toHaveLength(1);
      }),
      { numRuns: 40 },
    );
  });
});

describe("WIRE_3_live_api: nothing else is connected", () => {
  it("WIRE_3_getDecisions_and_decide_without_a_base_url_stay_NotBuilt_and_fetch_nothing", async () => {
    const spy = fakeApi({ pages: { "": page([entry(1)]) } });
    vi.stubGlobal("fetch", spy);
    await expect(createLiveApi().getDecisions()).rejects.toBeInstanceOf(NotBuilt);
    await expect(createLiveApi({ baseUrl: "  " }).getDecisions()).rejects.toBeInstanceOf(NotBuilt);
    await expect(createLiveApi().decide("depot")).rejects.toBeInstanceOf(NotBuilt);
    await expect(createLiveApi({ baseUrl: "" }).decide("depot")).rejects.toBeInstanceOf(NotBuilt);
    expect(spy).not.toHaveBeenCalled();
  });

  it("WIRE_3_undo_stays_NotBuilt_and_fetches_nothing_even_after_a_read_and_an_answer", async () => {
    const { api, spy, data } = await served([entry(1)]);
    const key = (data[0] as Decision).k;
    await api.decide(key);
    const before = spy.mock.calls.length;
    const err = await settle(api.undo(key));
    expect(err).toBeInstanceOf(NotBuilt);
    expect((err as NotBuilt).code).toBe("not_built");
    expect(spy.mock.calls.length).toBe(before);
  });

  it("WIRE_3_every_method_but_getLedger_getWorlds_getDecisions_and_decide_rejects_NotBuilt_and_never_touches_the_network", async () => {
    const spy = fakeApi({ pages: { "": page([entry(1)]) } });
    const api = live(spy);
    const args = callTable();
    const built = new Set([
      "getLedger",
      "getWorlds",
      "getDecisions",
      "decide",
      "startWorld",
      "getTeam",
      "getProfileSettings",
      "setPref",
    ]);
    for (const m of API_METHODS.filter((x) => !built.has(x))) {
      const err = await Promise.resolve(invoke(api, m, args)).then(
        (value) => ({ resolved: value }),
        (e: unknown) => e,
      );
      expect(err, `${m} must reject`).not.toHaveProperty("resolved");
      expect(err, `${m}`).toBeInstanceOf(NotBuilt);
    }
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("WIRE_3_parkApi: the url reaches getDecisions and decide", () => {
  it("WIRE_3_parkApi_with_a_url_reads_cards_on_the_global_fetch_answers_and_says_live", async () => {
    const spy = fakeApi({ pages: { "": page([entry(1)]) } });
    vi.stubGlobal("fetch", spy);
    const api = parkApi({ VITE_TILO_API_URL: `  ${BASE}/  ` });
    const read = await api.getDecisions();
    const url = urlsOf(spy)[0] as URL;
    expect(url.origin + url.pathname).toBe(`${BASE}/cards`);
    expect(read.source).toBe("live");
    expect(read.data).toHaveLength(1);
    const ack = await api.decide((read.data[0] as Decision).k);
    expect(ack.source).toBe("live");
    expect(urlsOf(spy, "POST")[0]?.pathname).toBe(
      `/worlds/${entry(1).world_id}/cards/${entry(1).card_id}/answer`,
    );
  });

  it("WIRE_3_parkApi_without_a_url_is_the_fixture_api_and_fetches_nothing", async () => {
    const spy = fakeApi({ pages: { "": page([entry(1)]) } });
    vi.stubGlobal("fetch", spy);
    const api = parkApi({});
    expect((await api.getDecisions()).source).toBe("fixture");
    expect((await api.decide("depot")).source).toBe("fixture");
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("WIRE_3_live_api_honesty: the live code cannot reach a fixture (HR-1..HR-7)", () => {
  it("WIRE_3_liveApi_still_imports_no_fixture", () => {
    const src = readFileSync(join(__dirname, "liveApi.ts"), "utf8");
    expect(src).not.toMatch(/from\s+["'](?:\.\.?\/)+(?:live\/)?fixtures/);
    expect(src).not.toMatch(/from\s+["'](?:\.\.?\/)+fixtureApi/);
  });

  it("WIRE_3_liveApi_holds_no_decision_text_or_scenario_copy_of_its_own", () => {
    const src = readFileSync(join(__dirname, "liveApi.ts"), "utf8");
    for (const f of fixtureDecisions) {
      for (const text of [f.title, f.body, f.yes, f.done, f.toast, f.approvedTitle]) {
        expect(src).not.toContain(text);
      }
    }
  });
});
