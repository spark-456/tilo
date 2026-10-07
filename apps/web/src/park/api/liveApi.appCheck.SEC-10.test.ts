// SEC-10: the Park app builds its own HttpClient (`createLiveApi`), so it needs the App Check getter too. Every live
// Park request (/costs, /worlds, /cards, the decision answer POST) carries `X-Firebase-AppCheck`; fixture mode makes
// no request and never asks for a token; a local host's real getter answers null, so no header and no call.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { createAppCheckTokenGetter } from "../../appcheck/appCheck";
import { createLiveApi } from "./liveApi";
import { parkApi } from "./select";
import type { DecisionKey } from "./types";

const BASE = "https://api.example.test";
const HEADER = "x-firebase-appcheck";
const token = ["fake", "app", "check", "park"].join(".");
const settle = (p: Promise<unknown>) => p.then(undefined, () => undefined);

const FEED_CARD = {
  id: "c_1",
  world_id: "w_1",
  kind: "needs_you",
  what_happened: "Something happened",
  why_it_matters: "It matters",
  options: [{ id: "go_on", label: "Go on", suggested: true }],
  gate: null,
  consent: null,
  created_at: "2026-10-07T09:30:00.000Z",
};

function recorder() {
  const seen: { url: string; method: string; headers: Headers }[] = [];
  const fetchFn = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    seen.push({ url, method: init?.method ?? "GET", headers: new Headers(init?.headers) });
    const body = url.includes("/cards?")
      ? { cards: [{ world_id: "w_1", card_id: "c_1", card: FEED_CARD }], next_cursor: null }
      : url.includes("/worlds?")
        ? { worlds: [], next_cursor: null }
        : url.endsWith("/answer")
          ? { outcome: "answered" }
          : {};
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
  return { seen, fetchFn };
}

describe("SEC-10 the Park live Api carries the App Check token", () => {
  it("SEC-10 every Park live request (costs, worlds, cards, the answer POST) has X-Firebase-AppCheck", async () => {
    const { seen, fetchFn } = recorder();
    const api = createLiveApi({ baseUrl: BASE, fetch: fetchFn, appCheckToken: async () => token });
    await settle(api.getLedger());
    await settle(api.getWorlds({}, []));
    const decisions = (await api.getDecisions()).data as { k: DecisionKey }[];
    await api.decide(decisions[0]?.k as DecisionKey);

    expect(seen.map((r) => `${r.method} ${new URL(r.url).pathname}`)).toEqual([
      "GET /costs",
      "GET /worlds",
      "GET /cards",
      "POST /worlds/w_1/cards/c_1/answer",
    ]);
    expect(seen.filter((r) => r.headers.get(HEADER) !== token)).toEqual([]);
  });

  it("SEC-10 parkApi hands its getter to the live Api and never asks it in fixture mode", async () => {
    const { seen, fetchFn } = recorder();
    vi.stubGlobal("fetch", fetchFn);
    try {
      const getter = vi.fn(async () => token);
      const live = parkApi({ VITE_TILO_API_URL: BASE }, getter);
      await settle(live.getWorlds({}, []));
      expect(seen[0]?.headers.get(HEADER)).toBe(token);

      const fixtureGetter = vi.fn(async () => token);
      for (const env of [{}, { VITE_TILO_API_URL: "" }, { VITE_TILO_API_URL: "  " }]) {
        const api = parkApi(env, fixtureGetter);
        await api.getWorlds({}, []);
      }
      expect(fixtureGetter).not.toHaveBeenCalled();
      expect(seen).toHaveLength(1); // fixture mode made no request
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("SEC-10 on a local host the real getter answers null: no header, no Google call", async () => {
    const { seen, fetchFn } = recorder();
    const api = createLiveApi({
      baseUrl: BASE,
      fetch: fetchFn,
      appCheckToken: createAppCheckTokenGetter({ hostname: "localhost" }),
    });
    await settle(api.getWorlds({}, []));
    expect(seen).toHaveLength(1);
    expect(seen[0]?.headers.has(HEADER)).toBe(false);
  });

  it("SEC-10 without a getter a Park request carries no header", async () => {
    const { seen, fetchFn } = recorder();
    await settle(createLiveApi({ baseUrl: BASE, fetch: fetchFn }).getWorlds({}, []));
    expect(seen[0]?.headers.has(HEADER)).toBe(false);
  });

  it("SEC-10 the Park provider takes the page's getter from ClientProvider and gives it to parkApi", () => {
    const text = readFileSync(join(__dirname, "..", "app", "context.tsx"), "utf8");
    expect(text).toMatch(/\{[^}]*\bappCheckToken\b[^}]*\} from "..\/..\/api\/ClientProvider"/);
    expect(text).toMatch(/parkApi\([^)]*appCheckToken\)/);
    const provider = readFileSync(join(__dirname, "..", "..", "api", "ClientProvider.tsx"), "utf8");
    expect(provider).toMatch(
      /createAppCheckTokenGetter\(\{ hostname: window\.location\.hostname \}\)/,
    );
  });
});
